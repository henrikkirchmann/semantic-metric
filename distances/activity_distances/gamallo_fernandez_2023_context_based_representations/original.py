import os
import shutil

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torchmetrics
import lightning as pl
from lightning.pytorch.callbacks import ModelCheckpoint, TQDMProgressBar, EarlyStopping
from torch.utils.data import DataLoader

#from logger import EmbGeneratorLogger
from pandas_dataset import EventlogDataset
from utils import DataFrameFields, Config, EmbType

torch.manual_seed(123)
np.random.seed(123)

import csv
from datetime import datetime, timedelta
import os


class AEracDataset(torch.utils.data.Dataset):
    def __init__(self, dataset: pd.DataFrame, num_categories: int, win_size: int):
        self.dataset = dataset.reset_index()  # Not drop index
        self.num_categories = num_categories
        self.win_size = win_size

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        event = self.dataset.iloc[idx]
        trace = self.dataset[self.dataset[DataFrameFields.CASE_COLUMN] == event[DataFrameFields.CASE_COLUMN]]
        context = trace.loc[idx - self.win_size: idx + self.win_size][DataFrameFields.ACTIVITY_COLUMN].to_numpy()
        # Store the first index of the trace
        start_idx = trace.iloc[0]['index']
        # Store the last index of the trace
        end_idx = trace.iloc[len(trace) - 1]['index']

        vectorized_context = []
        for event in context:
            vectorized_event = np.zeros(self.num_categories)
            vectorized_event[event] = 1
            vectorized_context.append(vectorized_event)
        vectorized_context = torch.tensor(np.array(vectorized_context))

        # Pre-padding
        pre_pad_len = start_idx - (idx - self.win_size)
        if pre_pad_len > 0:
            pre_pad_tensor = torch.zeros((pre_pad_len, self.num_categories))
            vectorized_context = torch.cat([pre_pad_tensor, vectorized_context])
        # Post-padding
        post_pad_len = (idx + self.win_size) - end_idx
        if post_pad_len > 0:
            post_pad_tensor = torch.zeros((post_pad_len, self.num_categories))
            vectorized_context = torch.cat([vectorized_context, post_pad_tensor])

        return vectorized_context


class ReconstructionError(torchmetrics.Metric):
    def __init__(self):
        super().__init__()
        self.add_state("acum_error", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("total", default=torch.tensor(0.0), dist_reduce_fx="sum")

        self.softmax = nn.Softmax(dim=2)

    def update(self, preds: torch.Tensor, target: torch.Tensor):
        preds = self.softmax(preds)

        _, idxs = target.max(dim=2)
        idxs = idxs.view(target.shape[0], -1, 1)

        err = 1 - preds.gather(2, idxs)

        self.acum_error += torch.sum(err)
        self.total += err.numel()

    def compute(self):
        return self.acum_error.float() / self.total


class Encoder(pl.LightningModule):
    def __init__(self, num_categories: int, win_size: int, emb_size: int):
        super().__init__()

        self.num_categories = num_categories
        self.win_size = win_size
        self.emb_size = emb_size

        self.input_acts_layer = nn.ModuleList()
        for i in range(2 * win_size + 1):
            self.input_acts_layer.append(
                nn.Linear(in_features=num_categories,
                          out_features=emb_size,
                          bias=False)
            )

        self.hidden_layer = nn.Linear(in_features=(2 * win_size + 1) * emb_size,
                                      out_features=emb_size,
                                      bias=False)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        # Each input activity passes through a different input
        # layer and the outputs are concatenated.
        concat_input_tensor = []
        for i, input_layer in enumerate(self.input_acts_layer):
            concat_input_tensor.append(input_layer(inputs[:, i]))

        concat_input_tensor = torch.cat(concat_input_tensor, dim=1)

        code = self.hidden_layer(concat_input_tensor)

        return code


class Decoder(pl.LightningModule):
    def __init__(self, num_categories: int, win_size: int, emb_size: int):
        super().__init__()

        self.num_categories = num_categories
        self.win_size = win_size
        self.emb_size = emb_size

        self.hidden_layer = nn.Linear(in_features=emb_size,
                                      out_features=(2 * win_size + 1) * emb_size,
                                      bias=False)

        self.output_acts_layer = nn.ModuleList()
        for i in range(2 * win_size + 1):
            self.output_acts_layer.append(
                nn.Linear(in_features=(2 * win_size + 1) * emb_size,
                          out_features=num_categories,
                          bias=False)
            )

    def forward(self, code: torch.Tensor) -> torch.Tensor:
        h = self.hidden_layer(code)

        concat_output_tensor = []
        for i, output_layer in enumerate(self.output_acts_layer):
            concat_output_tensor.append(output_layer(h).view(-1, 1, self.num_categories))

        concat_output_tensor = torch.cat(concat_output_tensor, dim=1)

        return concat_output_tensor


class AEracModel(pl.LightningModule):
    def __init__(self, num_categories: int, win_size: int, emb_size: int):
        super().__init__()

        self.num_categories = num_categories
        self.win_size = win_size
        self.emb_size = emb_size

        self.loss_function = torch.nn.BCEWithLogitsLoss()
        # self.accuracy = torchmetrics.Accuracy(task="multiclass", num_classes=num_categories)
        # self.f1_score = torchmetrics.classification.MulticlassF1Score(num_classes=num_categories,
        # average='macro')
        self.recons_error = ReconstructionError()

        self.encoder = Encoder(num_categories, win_size, emb_size)
        self.decoder = Decoder(num_categories, win_size, emb_size)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        code = self.encoder(inputs)
        reconstruction = self.decoder(code)

        return reconstruction

    def training_step(self, batch, batch_idx):
        inputs = batch
        reconstruction = self.forward(inputs.double())

        loss = self.loss_function(reconstruction, inputs)
        self.log("train_loss", loss.item(), on_step=True)

        '''
        inputs_idx = torch.flatten(inputs.argmax(dim=2))
        reconstruction = reconstruction.view(-1, self.num_categories)
        softmax = nn.Softmax(dim=1)

        accuracy = self.accuracy(reconstruction, inputs_idx)
        self.log("train_acc", accuracy, on_step=True)

        f1_score = self.f1_score(reconstruction, inputs_idx)
        self.log("train_f1", f1_score, on_step=True)

        return {'loss': loss, 'acc': accuracy, 'f1': f1_score}
        '''

        err = self.recons_error(reconstruction, inputs)
        self.log("train_err", err, on_step=True)
        return {"loss": loss, "error": err}

    def validation_step(self, batch, batch_idx):
        inputs = batch
        reconstruction = self.forward(inputs.double())

        loss = self.loss_function(reconstruction, inputs)
        self.log("val_loss", loss.item(), on_step=True)

        '''
        inputs_idx = torch.flatten(inputs.argmax(dim=2))
        reconstruction = reconstruction.view(-1, self.num_categories)
        softmax = nn.Softmax(dim=1)

        accuracy = self.accuracy(reconstruction, inputs_idx)
        self.log("val_acc", accuracy, on_step=True)

        f1_score = self.f1_score(reconstruction, inputs_idx)
        self.log("val_f1", f1_score, on_step=True)

        return {'loss': loss, 'acc': accuracy, 'f1': f1_score}
        '''

        err = self.recons_error(reconstruction, inputs)
        self.log("val_err", err, on_step=True)
        return {"loss": loss, "error": err}

    def test_step(self, batch, batch_idx):
        inputs = batch
        reconstruction = self.forward(inputs.double())

        loss = self.loss_function(reconstruction, inputs)
        self.log("test_loss", loss.item(), on_step=True)

        '''
        inputs_idx = torch.flatten(inputs.argmax(dim=2))
        reconstruction = reconstruction.view(-1, self.num_categories)
        softmax = nn.Softmax(dim=1)

        accuracy = self.accuracy(reconstruction, inputs_idx)
        self.log("test_acc", accuracy, on_step=True)

        f1_score = self.f1_score(reconstruction, inputs_idx)
        self.log("test_f1", f1_score, on_step=True)

        return {'acc': accuracy, 'f1': f1_score}
        '''

        err = self.recons_error(reconstruction, inputs)
        self.log("test_err", err, on_step=True)
        return {"los": loss, "error": err}

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=Config.LEARNING_RATE)

    def get_embeddings(self) -> dict:
        weights = list(self.encoder.input_acts_layer[self.win_size].parameters())[0].data

        # Create a dictionary to store the embeddings in
        embedding_dict = {}
        for i in range(self.num_categories):
            embedding_dict.update({
                i: weights[:, i].cpu().numpy()
            })

        return embedding_dict


def run_AErac_model(eventlog: EventlogDataset, emb_size: int, win_size: int,
                    ):
    control_flow_lists = [["A", "B", "C", "D", "E", "F", "G"],
                          ["A", "H", "D", "E", "F", "G"]]

    #logger: EmbGeneratorLogger
    torch.set_float32_matmul_precision('medium')

    # Create specific AErac datasets for each split
    csv_file, act_to_id_dict = transform_control_flow_lists_to_csv(control_flow_lists)

    eventlog = EventlogDataset(csv_file)

    train_dataset = AEracDataset(eventlog.df_train, eventlog.num_activities, win_size)
    #val_dataset = AEracDataset(eventlog.df_val, eventlog.num_activities, win_size)
    #test_dataset = AEracDataset(eventlog.df_test, eventlog.num_activities, win_size)

    # Create dataloaders for each split
    num_workers = os.cpu_count()
    train_loader = DataLoader(train_dataset, batch_size=Config.BATCH_SIZE,
                              shuffle=True, num_workers=num_workers)
    # Shuffling not needed in val/test loaders
    #val_loader = DataLoader(val_dataset, batch_size=Config.BATCH_SIZE, num_workers=num_workers)
    #test_loader = DataLoader(test_dataset, batch_size=num_workers)

    model = AEracModel(eventlog.num_activities, win_size, emb_size).double()

    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        dirpath="./models/" + eventlog.filename + "/embeddings/" + str(EmbType.AERAC) + "/checkpoints/",
        filename="best_model_winsize" + str(win_size) + "_embsize" + str(emb_size),
        save_top_k=1,
        mode="min"
    )

    early_stopping = EarlyStopping(monitor="val_loss", mode="min", patience=15)

    #accelerator='gpu', devices=1,
    trainer = pl.Trainer( max_epochs=Config.EPOCHS,
                         callbacks=[TQDMProgressBar(refresh_rate=20), early_stopping])

    try:
        shutil.rmtree("./models/" + eventlog.filename + "/embeddings/" + str(EmbType.AERAC) + "/checkpoints/")
    except FileNotFoundError:
        pass

    trainer.fit(model, train_loader)

    best_model = AEracModel.load_from_checkpoint(
        "./models/" + eventlog.filename + "/embeddings/" + str(EmbType.AERAC) + "/checkpoints/" +
        "best_model_winsize" + str(win_size) + "_embsize" + str(emb_size) + ".ckpt",
        num_categories=eventlog.num_activities,
        win_size=win_size,
        emb_size=emb_size
    ).double()

    #logger.log_console("Testing...")
    #dict_metrics = trainer.test(best_model, test_loader)

    embeddings_dict = best_model.get_embeddings()

    return
    #return dict_metrics[0]["test_loss_epoch"], embeddings_dict, dict_metrics[0]["test_err_epoch"]


def transform_control_flow_lists_to_csv(control_flow_lists):

    # Create a mapping from activities to unique integer IDs
    activity_set = sorted(set(activity for seq in control_flow_lists for activity in seq))
    activity_to_id = {activity: idx for idx, activity in enumerate(activity_set)}

    # Convert event log to CSV format
    start_time = datetime(1970, 1, 1)
    time_delta = timedelta(hours=1)

    events = []
    for case_id, activities in enumerate(control_flow_lists):
        for event_index, activity in enumerate(activities):
            timestamp = start_time + event_index * time_delta
            events.append([case_id, activity_to_id[activity], timestamp.isoformat() + "+00:00"])

    process_id = os.getpid()
    # Output CSV file name
    output_file = f"event_log_{process_id}.csv"

    # Write to CSV
    with open(output_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["CaseID", "Activity", "Timestamp"])
        writer.writerows(events)

    return output_file, activity_to_id
