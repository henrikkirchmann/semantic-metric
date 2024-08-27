import gc
import multiprocessing
import sys
from multiprocessing import Pool
from pathlib import Path
import random
import tracemalloc
import pm4py
from pm4py.objects.log.importer.xes import importer as xes_importer
from pm4py.statistics.variants.log import get as variants_module
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib import rc
from definitions import ROOT_DIR
import time
import psutil
from os import kill
from os import getpid
from signal import SIGKILL


from evaluation.data_util.util_activity_distances import get_alphabet, get_activity_distance_matrix_dict, get_log_control_flow_perspective_with_short_activity_names, get_obj_size, unresponsiveness_prediction

from evaluation.data_util.util_activity_distances_intrinsic import (
    get_log_control_flow_perspective, get_activities_to_replace,
    get_logs_with_replaced_activities_dict,
    get_knn_dict, get_precision_at_k
)

from evaluation.data_util.util_activity_distances_extrinsic import get_sublog_list


def evaluate_intrinsic(activity_distance_functions, log_list, w, sampling_size):

    for log_name in log_list:
        if log_name[:4] == "bpic" or log_name[:3] == "pdc":
            sublog_list = get_sublog_list(log_name)

            log_control_flow_perspective = [inner for outer in sublog_list for inner in outer]
        else:
            log = xes_importer.apply(ROOT_DIR + '/event_logs/' + log_name + '.xes')
            #pm4py.view_process_tree(pm4py.discover_process_tree_inductive(log))
            log_control_flow_perspective = get_log_control_flow_perspective(log)
            #print(get_obj_size(log_control_flow_perspective))
        alphabet = get_alphabet(log_control_flow_perspective)
        #log_control_flow_perspective = get_log_control_flow_perspective_with_short_activity_names(
            #log_control_flow_perspective, alphabet)
        print(get_obj_size(log_control_flow_perspective))


        #active
        alphabet = get_alphabet(log_control_flow_perspective)
        r = min(100,len(alphabet))
        #w = 10
        #sampling_size = 1
        #print(sampling_size)
        #del log
        #for activity_distance_function in activity_distance_functions:

        ########################
        # Intrinsic evaluation #
        ########################


        ''' 
        if unresponsiveness_prediction(get_obj_size(log_control_flow_perspective), len(alphabet), r, w):
            #set sampling size to high as possible, but enough room for not too much ram consumption take
            step_size = 1
            max_value = 100000
            for sampling_size_test in range(1, max_value + 1, step_size):
                if not unresponsiveness_prediction(get_obj_size(log_control_flow_perspective), len(alphabet), r, w,
                                                sampling_size_test):
                    sampling_size = sampling_size_test
                else:
                    if sampling_size is None:
                        sampling_size = 1
                        print("System might run out of memory.")
                    break

        print(sampling_size)
        #sampling_size = None
        '''


        combinations = [
            (
            different_activities_to_replace_count, activities_to_replace_with_count, log_control_flow_perspective, alphabet, activity_distance_functions, sampling_size)
            for different_activities_to_replace_count in range(1, r+1)
            for activities_to_replace_with_count in range(2, w+1)
        ]
        print(get_obj_size(combinations))
        # limit used cores, for system responsiveness
        total_cores = multiprocessing.cpu_count()

        # Calculate 75% of the available cores
        cores_to_use = int(total_cores * 0.75)

        # Ensure at least one core is used
        cores_to_use = max(1, cores_to_use)


        with Pool(processes=cores_to_use) as pool:
            results = pool.map(intrinsic_evaluation, combinations)


        print("------------------done")
        #return
        # Further memory cleanup after processing
        #del log_control_flow_perspective, combinations, alphabet, results
        #gc.collect()        #pool.close()
        #pool.join()
        #memory_info = psutil.virtual_memory()
        # memory_info.total >> 30
        # Get the amount of free memory
        #free_memory = memory_info.free
        #free_memory = free_memory / (1024.0 ** 3)
        #print(free_memory)
        output_file = ROOT_DIR + "/results/activity_distances/intrinsic/"+str(log_name) +"_r:" + str(r) + "_w:" + str(w) + "_sampling:"+ str(sampling_size) + ".txt"

        activity_distance_function_index = 0
        for activity_distance_function in activity_distance_functions:
            results_per_activity_distance_function = list()
            for result in results:
                #if result[activity_distance_function_index][4] == activity_distance_function:
                results_per_activity_distance_function.append(result[activity_distance_function_index])
            visualization_intrinsic_evaluation(results_per_activity_distance_function, activity_distance_function, log_name, r, w, sampling_size, output_file)
            load_visualization_intrinsic_evaluation(results_per_activity_distance_function, activity_distance_function, log_name, r, w, sampling_size, output_file)
            activity_distance_function_index = activity_distance_function_index + 1


def intrinsic_evaluation(args):
    #tracemalloc.start()
    different_activities_to_replace_count, activities_to_replace_with_count, log_control_flow_perspective, alphabet, activity_distance_function_list, sampling_size = args
    # 1: get the activities that we want to replace in each run
    activities_to_replace_in_each_run_list = get_activities_to_replace(alphabet, different_activities_to_replace_count, sampling_size)
    #memory_info = psutil.virtual_memory()
    #memory_info.total >> 30
    # Get the amount of free memory
    #free_memory = memory_info.free
    #free_memory = free_memory / (1024.0 ** 3)

    #del activities_to_replace_in_each_run_list, different_activities_to_replace_count, activities_to_replace_with_count, log_control_flow_perspective, alphabet, activity_distance_function_list, sampling_size


    print("start ---- r:" + str(different_activities_to_replace_count) + " w: "+str(activities_to_replace_with_count) )
          #+ "free memory:" + str(free_memory))
    #1.1: limit the number of logs for performance
    if len(activities_to_replace_in_each_run_list) >= sampling_size:
        #print(activities_to_replace_in_each_run_list)
        activities_to_replace_in_each_run_list = random.sample(list(activities_to_replace_in_each_run_list), sampling_size)
        set(activities_to_replace_in_each_run_list)
    results_list = list()



    for activity_distance_function in activity_distance_function_list:
        activity_distance_function = [activity_distance_function]
        precision_at_w_minus_1_list = list()
        precision_at_1_list = list()
        for activities_to_replace in activities_to_replace_in_each_run_list:
            # 2: replace activities
            logs_with_replaced_activities_dict = get_logs_with_replaced_activities_dict(
                [activities_to_replace], log_control_flow_perspective,
                different_activities_to_replace_count, activities_to_replace_with_count
            )
            #del logs_with_replaced_activities_dict
            #gc.collect()
            #print(str((time.time() - start_time)) +" seconds ---" + " r:" + str(different_activities_to_replace_count) + " w: "+str(activities_to_replace_with_count))
            #return list()
            # 3: compute for all logs all activity distance matrices
            n_gram_size_bose_2009 = 3

            activity_distance_matrix_dict = get_activity_distance_matrix_dict(
                activity_distance_function, logs_with_replaced_activities_dict, n_gram_size_bose_2009
            )

            # Clean up to save memory
            #del logs_with_replaced_activities_dict
            #gc.collect()


            if "Bose 2009 Substitution Scores" == activity_distance_function[0]:
                reverse=True #high values = high similarity
            else:
                reverse=False #high values = high distances

            # 4: evaluation of all activity distance matrices
            w_minus_one_nn_dict = get_knn_dict(activity_distance_matrix_dict, activities_to_replace_with_count, reverse, activities_to_replace_with_count-1)
            precision_at_w_minus_1_dict = get_precision_at_k(w_minus_one_nn_dict, activity_distance_function)
            #(precision_at_w_minus_1_dict)
            precision_at_w_minus_1_list.append(precision_at_w_minus_1_dict[activity_distance_function[0]])

            one_nn_dict = get_knn_dict(activity_distance_matrix_dict, activities_to_replace_with_count, reverse, 1)
            precision_at_1_dict = get_precision_at_k(one_nn_dict, activity_distance_function)
            precision_at_1_list.append(precision_at_1_dict[activity_distance_function[0]])
        precision_at_w_minus_1 = sum(precision_at_w_minus_1_list)/len(precision_at_w_minus_1_list)
        precision_at_1 = sum(precision_at_1_list)/len(precision_at_1_list)
        results_list.append((different_activities_to_replace_count, activities_to_replace_with_count, precision_at_w_minus_1, precision_at_1))

    #precision = precision_at_k_dict["De Koninck 2018 act2vec"]

    #memory_info = psutil.virtual_memory()
    #memory_info.total >> 30 #covert to GigaByte
    # Get the amount of free memory
    #free_memory = memory_info.free
    #free_memory = free_memory / (1024.0 ** 3)

    #results_list = list()
    print("end ---- r:" + str(different_activities_to_replace_count) + " w: "+str(activities_to_replace_with_count) + " sampling size: " + str(sampling_size))
    #snapshot = tracemalloc.take_snapshot()
    #top_stats = snapshot.statistics('lineno')

    #print("[Top 10 memory-consuming lines]")
    #results_list = list()
    #for stat in top_stats[:10]:
    #    print(stat)
    #tracemalloc.stop()
    return results_list

def visualization_intrinsic_evaluation(results, activity_distance_function, log_name, r, w, sampling_size, output_file):
    # Create DataFrame from results
    df = pd.DataFrame(results, columns=['r', 'w', 'precision@w-1', 'precision@1'])

    # Generate the file name incorporating all function arguments if no output_file is provided
    csv = f"{log_name}_distfunc_{activity_distance_function}_r{r}_w{w}_samplesize_{sampling_size}.csv"

    # Ensure that the file name is valid and does not contain invalid characters (especially for file systems)
    csv = csv.replace("/", "_").replace("\\", "_")

    # Save the DataFrame to a CSV file
    df.to_csv(csv, index=False)

    ''' 
    #heat map precision@w-1
    result = df.pivot(index='w', columns='r', values='precision@w-1')

    average_value = result.values.mean()
    print("The average precision@w-1 is: " + str(average_value) + " " + activity_distance_function)
    with open(output_file, "a") as file:
        file.write("The average precision@w-1 is: " + str(average_value) + " " + activity_distance_function + "\n")
        file.write("\n")
    # Plotting
    rc('font', **{'family': 'serif', 'size': 20*3.5})
    f, ax = plt.subplots(figsize=(17 + 17*int(r/17), 20))
    cmap = sns.cm.rocket_r
    ax = sns.heatmap(result, cmap=cmap, vmin=0, vmax=1, linewidth=.5)
    ax.invert_yaxis()
    ax.set_title("precision@w-1 for " + log_name + " with max sampling size " + str(sampling_size) +"\n" +activity_distance_function, pad=20)
    Path(ROOT_DIR + "/results/activity_distances/intrinsic/precision_at_k").mkdir(parents=True, exist_ok=True)
    plt.savefig(ROOT_DIR + "/results/activity_distances/intrinsic/precision_at_k/" + "pre_" + activity_distance_function + "_" + log_name + "_r:" + str(r) + "_w:" + str(w) + "_sampling:"+ str(sampling_size) + ".pdf", format="pdf", transparent=True)
    plt.show()

    #heat map precision@1
    result = df.pivot(index='w', columns='r', values='precision@1')
    average_value = result.values.mean()
    print("The average Nearest Neighbor is: " + str(average_value) + " " + activity_distance_function)
    with open(output_file, "a") as file:
        file.write("The average Nearest Neighbor is: " + str(average_value) + " " + activity_distance_function + "\n")
        file.write("\n")
    # Plotting
    rc('font', **{'family': 'serif', 'size': 20*3})
    f, ax = plt.subplots(figsize=(17+ 17*int(r/17), 20))
    cmap = sns.cm.rocket_r
    ax = sns.heatmap(result, cmap=cmap, vmin=0, vmax=1, linewidth=.5)
    ax.invert_yaxis()
    ax.set_title("Nearest Neighbor for " + log_name + " with max sampling size " + str(sampling_size) + "\n" +activity_distance_function, pad=20)
    Path(ROOT_DIR + "/results/activity_distances/intrinsic/nn").mkdir(parents=True, exist_ok=True)
    plt.savefig(ROOT_DIR + "/results/activity_distances/intrinsic/nn/" + "nn" + activity_distance_function + "_" + log_name + "_r:" + str(r) + "_w:" + str(w) + "_sampling:"+ str(sampling_size) + ".pdf", format="pdf", transparent=True)
    plt.show()
    '''

def load_visualization_intrinsic_evaluation(results, activity_distance_function, log_name, r, w, sampling_size, output_file):
    # Specify the file name that was used earlier
    file_name = "pdc_2022_distfunc_De Koninck 2018 act2vec CBOW_r17_w100_samplesize_1.csv"
    # Load the DataFrame from the CSV file
    df = pd.read_csv(file_name)

    #heat map precision@w-1
    result = df.pivot(index='w', columns='r', values='precision@w-1')

    average_value = result.values.mean()
    print("The average precision@w-1 is: " + str(average_value) + " " + activity_distance_function)
    with open(output_file, "a") as file:
        file.write("The average precision@w-1 is: " + str(average_value) + " " + activity_distance_function + "\n")
        file.write("\n")
    # Plotting
    rc('font', **{'family': 'serif', 'size': 20*3.5})
    f, ax = plt.subplots(figsize=(17 + 17*int(r/17), 20))
    cmap = sns.cm.rocket_r
    ax = sns.heatmap(result, cmap=cmap, vmin=0, vmax=1, linewidth=.5)
    ax.invert_yaxis()
    ax.set_title("precision@w-1 for " + log_name + " with max sampling size " + str(sampling_size) +"\n" +activity_distance_function, pad=20)
    Path(ROOT_DIR + "/results/activity_distances/intrinsic/precision_at_k").mkdir(parents=True, exist_ok=True)
    plt.savefig(ROOT_DIR + "/results/activity_distances/intrinsic/precision_at_k/" + "pre_" + activity_distance_function + "_" + log_name + "_r:" + str(r) + "_w:" + str(w) + "_sampling:"+ str(sampling_size) + ".pdf", format="pdf", transparent=True)
    plt.show()

    #heat map precision@1
    result = df.pivot(index='w', columns='r', values='precision@1')
    average_value = result.values.mean()
    print("The average Nearest Neighbor is: " + str(average_value) + " " + activity_distance_function)
    with open(output_file, "a") as file:
        file.write("The average Nearest Neighbor is: " + str(average_value) + " " + activity_distance_function + "\n")
        file.write("\n")
    # Plotting
    rc('font', **{'family': 'serif', 'size': 20*3})
    f, ax = plt.subplots(figsize=(17+ 17*int(r/17), 20))
    cmap = sns.cm.rocket_r
    ax = sns.heatmap(result, cmap=cmap, vmin=0, vmax=1, linewidth=.5)
    ax.invert_yaxis()
    ax.set_title("Nearest Neighbor for " + log_name + " with max sampling size " + str(sampling_size) + "\n" +activity_distance_function, pad=20)
    Path(ROOT_DIR + "/results/activity_distances/intrinsic/nn").mkdir(parents=True, exist_ok=True)
    plt.savefig(ROOT_DIR + "/results/activity_distances/intrinsic/nn/" + "nn" + activity_distance_function + "_" + log_name + "_r:" + str(r) + "_w:" + str(w) + "_sampling:"+ str(sampling_size) + ".pdf", format="pdf", transparent=True)
    plt.show()




if __name__ == '__main__':



    ##############################################################################
    # intrinsic - activity_distance_functions we want to evaluate
    activity_distance_functions = list()
    activity_distance_functions.append("Bose 2009 Substitution Scores")
    activity_distance_functions.append("De Koninck 2018 act2vec CBOW")
    #activity_distance_functions.append("De Koninck 2018 act2vec skip-gram")
    ##############################################################################
    w = 50
    sampling_size = 3
    print(sampling_size)
    ##############################################################################
    # intrinsic - event logs we want to evaluate
    log_list = list()
    #log_list.append("repairExample")
    #log_list.append("bpic_2015")
    log_list.append("Sepsis")
    #log_list.append("Road_Traffic_Fine_Management_Process")
    #log_list.append("bpic_2015")
    #log_list.append("pdc_2016")
    #log_list.append("BPIC15_1")
    #log_list.append("pdc_2022")
    #log_list.append("pdc_2017")
    #log_list.append("pdc_2020")
    #log_list.append("BPI Challenge 2017")

    #log_list.append("BPI Challenge 2017")
    #log_list.append("wabo_all")


    print(log_list)


    #log_list.append("2019_1")
    ##############################################################################

    ##############################################################################
    # intrinsic - event logs we want to evaluate
    evluation_measure_list = list()
    #evluation_measure_list.append("precision@w-1")
    #evluation_measure_list.append("precision@1")
    ##############################################################################


    evaluate_intrinsic(activity_distance_functions, log_list, w, sampling_size)








