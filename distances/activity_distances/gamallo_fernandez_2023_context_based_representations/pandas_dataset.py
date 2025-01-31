import os
import pandas as pd
import numpy as np
from pathlib import Path
from utils import DataFrameFields


class EventlogDataset:
    """
    Custom Dataset for .csv eventlogs (Pandas DataFrame)
    """
    filename: str
    directory: Path

    df_train: pd.DataFrame
    df_val: pd.DataFrame
    df_test: pd.DataFrame

    num_activities: int
    num_resources: int

    def __init__(self, csv_path: str, cv_fold: int = None, read_test: bool = True):
        """
        Creates the EventlogDataset and read the eventlog from the path
        :param csv_path: Path to the .csv file with the eventlog
        :param cv_fold: Number of fold if a cross-validation fold is read
        :param read_test: Boolean indicating if read test split is necessary
        """

        self.filename = Path(csv_path).stem
        self.directory = Path(csv_path).parent

        self.df_train = self.read_split('train', cv_fold)
        ''' 
        self.df_val = self.read_split('val', cv_fold)
        if read_test:
            self.df_test = self.read_split('test', cv_fold)
        '''

        self.num_activities = self.get_num_activities(use_test=read_test)
        #if DataFrameFields.RESOURCE_COLUMN in self.df_train.columns:
        #    self.num_resources = self.get_num_resources(use_test=read_test)

    def read_split(self, path) -> pd.DataFrame:
        """
        Read the .csv file corresponding to the split
        :param split: Partition to read: train, val or test
        :param cv_fold: Number of fold if a cross-validation fold is read
        :return: Pandas DataFrame with the eventlog read
        """

        df = pd.read_csv(path, index_col=0)
        df[DataFrameFields.ACTIVITY_COLUMN] = df[DataFrameFields.ACTIVITY_COLUMN]
        df[DataFrameFields.ACTIVITY_COLUMN] = df[DataFrameFields.ACTIVITY_COLUMN].astype('category')
        df[DataFrameFields.TIMESTAMP_COLUMN] = df[DataFrameFields.TIMESTAMP_COLUMN].astype('datetime64[ns]')
        df = df.reset_index(drop=True)
        return df

    def get_num_activities(self, use_test: bool = False):
        """
        Gets the number of unique activities. By default, use only
        train and validation sets
        :param use_test: Boolean indicating if use test set
        :return: Number of unique activities in the eventlog
        """

        all_activities = self.df_train[DataFrameFields.ACTIVITY_COLUMN]
        #if use_test:
        #    all_activities = pd.concat([all_activities, self.df_test[DataFrameFields.ACTIVITY_COLUMN]])
        all_activities = np.sort(np.unique(all_activities))
        num_activities = all_activities[-1].item() + 1

        return num_activities

    def get_num_resources(self, use_test: bool = False):
        """
        Gets the number of unique resources. By default, use only
        train and validation sets
        :param use_test: Boolean indicating if use test set
        :return: Number of unique resources in the eventlog
        """

        all_resources = pd.concat([self.df_train[DataFrameFields.RESOURCE_COLUMN],
                                   self.df_val[DataFrameFields.RESOURCE_COLUMN]])
        if use_test:
            all_resources = pd.concat([all_resources, self.df_test[DataFrameFields.RESOURCE_COLUMN]])
        all_resources = np.sort(np.unique(all_resources))
        num_resources = all_resources[-1].item() + 1

        return num_resources

    def get_num_events(self, split: str) -> int:
        """
        Gets the number of events in the eventlog
        :param split: Partition to read: train, val or test
        :return: The number of events
        """
        if split == 'train':
            return len(self.df_train.index)
        if split == 'val':
            return len(self.df_val.index)
        if split == 'test':
            return len(self.df_test.index)

    def get_num_cases(self, split: str) -> int:
        """
        Gets the number of cases in the eventlog
        :param split: Partition to read: train, val or test
        :return: The number of cases
        """

        if split == 'train':
            return len(self.df_train.groupby(DataFrameFields.CASE_COLUMN))
        if split == 'val':
            return len(self.df_val.groupby(DataFrameFields.CASE_COLUMN))
        if split == 'test':
            return len(self.df_test.groupby(DataFrameFields.CASE_COLUMN))

