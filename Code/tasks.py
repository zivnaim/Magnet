import csv
import datetime
import os
import time
from random import sample
import pandas as pd

import networkx as nx

from BipartiteProbabilisticMatching.matching_solutions import MatchingProblem

import numpy as np
from shutil import copy
from sklearn.metrics import f1_score, precision_score, recall_score

from PathwayProbabilitiesCalculation.pathway_probabilities_calculation import iterate_by_layers, normalize_probs_matrix, \
    top5_probs_to_csv
from PathwayProbabilitiesCalculation.probabilities_using_embeddings import fun_3, node2vec_embed, createKD, \
    get_closest_neighbors
from multipartite_lol_graph import MultipartiteLol
from StaticGraphEmbeddings.evaluation_tasks.calculate_static_embeddings import ogre_static_embeddings

SEP = '/'


"""
#### README ####
This file is for implementing the actual run and evaluation of each of the tasks.
For each task we implemented the followings:
1. prepare() method: We call it before the run to initialize some properties.
2. run() method: Run the task using the appropriate dir of python code. This method save the results to the Results dir!
3. eval() method: Eval the task, using ONLY result files from the Results dir.
4. __str__() method: A string representation for the task.
"""

class Task:
    def __init__(self, results_root='.', task_params=None):
        self.results_root = results_root
        self.task_params = task_params
        self.destination = None
        self.results_dir = None
        self.results_files = None
        self.runtime_file = None
        self.memory_file = None
        self.eval_files = None
        self.data_name = None
        self.run_string_list = None
        self.f1_string_list = None
        self.eval_methods = None
        self.use_task_1_results = False
        self.scores = []
        self.runtimes = []
        self.ids = []


        if not self.task_params:
            self.task_params = {}

    def prepare(self, graph_params, eval=False):
        self.data_name = graph_params.data_name
        self.destination = SEP.join([self.results_root, "task_" + str(self), self.data_name])
        beta_str = str(self.task_params['beta'][0]) + '_beta' if 'beta' in self.task_params.keys() else ''
        self.run_string_list = [self.task_params.get('embedding', ''), beta_str]#str(round(float(self.task_params.get('param_str', '')), 1))]
        self.run_string_list = [string for string in self.run_string_list if string]
        self.f1_string_list = [self.task_params.get('embedding', ''), str(self.task_params.get('f1_threshold', '')), beta_str]
        self.f1_string_list = [string for string in self.f1_string_list if string]
        self.runtime_file = SEP.join([self.destination, "_".join(self.run_string_list + ["runtime.csv"])])
        self.memory_file = SEP.join([self.destination, "_".join(self.run_string_list + ["memory.csv"])])
        results_destination = SEP.join([self.destination, "_".join(self.run_string_list + ["results"])])
        self.results_dir = SEP.join([results_destination, "_".join([graph_params.name, "results"])])
        if not os.path.exists(self.results_dir) and not eval:
            os.makedirs(self.results_dir)
        elif not os.path.exists(self.results_dir):
            raise Exception(f"results not found: {self.results_dir}")
        self.results_files = self.get_results_files(graph_params, eval=eval)
        self.eval_files = self.get_eval_files()
        self.ids.append(graph_params.id)

    def get_results_files(self, graph_params, eval=False):
        if eval:
            return [SEP.join([self.results_dir, file_name]) for file_name in os.listdir(self.results_dir) if
                    'gt.csv' not in file_name]
        else:
            return [SEP.join([self.results_dir, file_name]) for file_name in os.listdir(graph_params.path) if
                    'gt.csv' not in file_name]

    def get_eval_files(self):
        eval_files = {}
        for method in self.eval_methods:
            if method == 'f1_score':
                eval_files[method] = SEP.join([self.destination, "_".join(self.f1_string_list + [method]) + ".csv"])
                eval_files['best_'+method] = SEP.join([self.destination, 'best_'+method + ".csv"])
            else:
                eval_files[method] = SEP.join([self.destination, "_".join(self.run_string_list + [method]) + ".csv"])
        return eval_files

    def save_gt(self, graph_params):
        copy(graph_params.gt, self.results_dir)

    def save_attributes(self, memory):
        self.save_to_file([['x'] + self.ids, [self.data_name] + self.runtimes], self.runtime_file)
        self.save_to_file([['x'] + self.ids, [self.data_name] + memory], self.memory_file)

    def save_eval(self, method):
        self.save_to_file([['x'] + self.ids, [self.data_name] + self.scores], self.eval_files[method])

    def save_best(self, method):
        self.save_to_file([['x'] + self.ids, [self.data_name] + self.scores, [], self.task_params.keys(),
                           self.task_params.values()], self.eval_files['best_'+method])

    def clean(self):
        self.scores = []
        self.runtimes = []
        self.ids = []

    def save_to_file(self, lines_list, path):
        with open(path, 'w', newline='') as file:
            wr = csv.writer(file)
            for line in lines_list:
                wr.writerow(line)


class BipartiteProbabilisticMatchingTask(Task):
    """
    This is the first algorithm in MAGNET (also called here task_1).
    This is the Bipartite Probabilistic Matching method, using code from BipartiteProbabilisticMatching dir.
    This gets data from Results/data, and output results to Results/task_1 .
    """
    def __init__(self, results_root='.', task_params=None):
        super().__init__(results_root, task_params)
        self.eval_methods = ['avg_acc', 'winner_acc', 'top5_acc', 'f1_score']

    def run(self, graph_params):
        start = time.time()
        print("Running task", str(self), 'on graph', graph_params.name)
        self.prepare(graph_params)

        # file_names = sys.argv[2:len(sys.argv)]
        first_stage_params = {"rho_0": self.task_params.get("rho_0", 0.3),
                              "rho_1": self.task_params.get("rho_1", 0.6),
                              "epsilon": self.task_params.get("epsilon", 1e-2)}
        # first_stage_saving_paths = [os.path.join("..", "BipartiteProbabilisticMatching", "results",
        #                                          "yoram_network_1",
        #                                          f"yoram_network_1_graph_{g}.csv") for g in range(1, 4)]
        for graph_path, first_saving_path in zip(graph_params.files, self.results_files):
            first_saving_path_01 = first_saving_path[:-4] + "_01" + first_saving_path[-4:]
            first_saving_path_10 = first_saving_path[:-4] + "_10" + first_saving_path[-4:]
            MatchingProblem(graph_path, "flow_numeric", first_stage_params, first_saving_path_01, row_ind=0, col_ind=1)
            MatchingProblem(graph_path, "flow_numeric", first_stage_params, first_saving_path_10, row_ind=1, col_ind=0)

        # plot_toy_graphs(file_names=file_names, name="small", graphs_directions=[(0, 1)], problem=[4, 16])
        # plot_toy_graphs(file_names=[first_saving_path_01], name="small_01", directed=True, graphs_directions=[(0, 1)], header=True, integer=False, problem=[0.18, 0.79])
        # plot_toy_graphs(file_names=[first_saving_path_10], name="small_10", directed=True, graphs_directions=[(1, 0)], header=True, integer=False, problem=[0.84, 0.17])
        if graph_params.gt:
            self.save_gt(graph_params)
        self.runtimes.append(time.time() - start)

    def eval(self, graph_params, method):
        # print("Evaluating task", str(self), 'on graph', graph_params.name, 'with method', method)
        if method not in self.eval_methods:
            raise Exception('method ' + method + ' not found!')
        self.prepare(graph_params, eval=True)

        f1_threshold = self.task_params.get('f1_threshold', 0)
        files_scores = []
        for file, from_to_id in zip(self.results_files, graph_params.from_to_ids):
            with open(file, "r", newline='') as csvfile:
                probs = {}
                datareader = csv.reader(csvfile)
                next(datareader, None)  # skip the headers
                for edge in datareader:
                    probs[edge[0]] = probs.get(edge[0], {})
                    probs[edge[0]][edge[1]] = float(edge[2])
                for key, value in probs.items():
                    probs[key] = dict(sorted(value.items(), key=lambda item: item[1], reverse=True))

                gt_list = [(i, i) for i in probs.keys()]
                if graph_params.gt:
                    with open(graph_params.gt, "r", newline='') as csvfile:
                        file_data = list(csv.reader(csvfile))
                        gt_list = [(row[from_to_id[0]], row[from_to_id[1]]) for row in file_data]
                gt = {a: b for a, b in gt_list}

                if method == 'avg_acc':
                    scores = [neighbors.get(gt.get(node, '-1'), 0) for node, neighbors in probs.items()]
                    score = np.mean(scores)
                elif method == 'winner_acc':
                    scores = [1 if gt.get(node, '-1') == list(neighbors.keys())[0] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'top5_acc':
                    scores = [1 if gt.get(node, '-1') in list(neighbors.keys())[:5] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'f1_score':
                    # pred_test = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items()]
                    pred = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items() if
                            list(neighbors.values())[0] > f1_threshold]
                    all = set(gt_list + pred)
                    y_true = [int(a in gt_list) for a in all]
                    y_pred = [int(a in pred) for a in all]
                    score = f1_score(y_true, y_pred)
                else:
                    raise Exception('method ' + method + ' not found!')
                files_scores.append(score)
        final_score = round(np.mean(files_scores), 3)
        self.scores.append(final_score)

    def __str__(self):
        return '1_BipartiteProbabilisticMatching'

class BipartiteNaiveTask(BipartiteProbabilisticMatchingTask):
    """
    This is the first task in MAGNET, only using naive algorithm (also called here task_5).
    This is the Bipartite Probabilistic Matching method, using code from BipartiteProbabilisticMatching dir.
    This gets data from Results/data, and output results to Results/task_5 .
    """
    def run(self, graph_params):
        start = time.time()
        print("Running task",str(self), 'on graph', graph_params.name)
        self.prepare(graph_params)

        # file_names = sys.argv[2:len(sys.argv)]
        first_stage_params = {"rho_0": self.task_params.get("rho_0", 0.3),
                              "rho_1": self.task_params.get("rho_1", 0.6),
                              "epsilon": self.task_params.get("epsilon", 1e-2)}
        # first_stage_saving_paths = [os.path.join("..", "BipartiteProbabilisticMatching", "results",
        #                                          "yoram_network_1",
        #                                          f"yoram_network_1_graph_{g}.csv") for g in range(1, 4)]
        for graph_path, first_saving_path in zip(graph_params.files, self.results_files):
            first_saving_path_01 = first_saving_path[:-4] + "_01" + first_saving_path[-4:]
            first_saving_path_10 = first_saving_path[:-4] + "_10" + first_saving_path[-4:]
            # MatchingProblem(graph_path, "flow_numeric", first_stage_params, first_saving_path_01, row_ind=0, col_ind=1)
            # MatchingProblem(graph_path, "flow_numeric", first_stage_params, first_saving_path_10, row_ind=1, col_ind=0)
            MatchingProblem(graph_path, "null_model", first_stage_params, first_saving_path_01, row_ind=0, col_ind=1)
            MatchingProblem(graph_path, "null_model", first_stage_params, first_saving_path_10, row_ind=1, col_ind=0)

        # plot_toy_graphs(file_names=file_names, name="small", graphs_directions=[(0, 1)], problem=[4, 16])
        # plot_toy_graphs(file_names=[first_saving_path_01], name="small_01", directed=True, graphs_directions=[(0, 1)], header=True, integer=False, problem=[0.18, 0.79])
        # plot_toy_graphs(file_names=[first_saving_path_10], name="small_10", directed=True, graphs_directions=[(1, 0)], header=True, integer=False, problem=[0.84, 0.17])
        if graph_params.gt:
            self.save_gt(graph_params)
        self.runtimes.append(time.time() - start)

    # def eval(self, graph_params, method):
    #     pass

    def __str__(self):
        return '5_BipartiteNaive'


class MultipartiteCommunityDetectionTask(Task):
    """
    This is the second task in MAGNET (also called here task_2).
    This is the Multipartite Community Detection method, using code from MultipartiteCommunityDetection dir.
    This gets data from Results/task_1, and output results to Results/task_2 .
    """
    def __init__(self, results_root='.', task_params=None):
        super().__init__(results_root, task_params)
        self.use_task_1_results = True
        self.greedy = False
        self.eval_methods = ['full_avg_acc', 'all_avg_acc', 'f1_score', 'fixed_f1_score']


    def run(self, graph_params):
        start = time.time()
        print("Running task", str(self), 'on graph', graph_params.name)
        self.prepare(graph_params)

        lol = True
        if lol:
            from MultipartiteCommunityDetection.run_louvain_lol import run_louvain
        else:
            from MultipartiteCommunityDetection.run_louvain import run_louvain, load_graph_from_files
        np.random.seed(42)

        if lol:
            graph = MultipartiteLol()
            graph.convert_with_csv(graph_params.files, graph_params.from_to_ids)
            graph.set_nodes_type_dict()
        else:
            graph = load_graph_from_files(graph_params.files, graph_params.from_to_ids, has_title=True, cutoff=0.0)

        num_of_groups = self.task_params.get('num_of_groups', 3)
        params = {"graph": graph,
                  "dump_name": self.results_files[0],
                  "res": self.task_params.get("res", 1.),
                  "beta": self.task_params.get("beta", [10.] * num_of_groups),
                  "assess": self.task_params.get("assess", False),
                  "ground_truth": self.task_params.get("ground_truth", None),
                  "draw": self.task_params.get("draw", False),
                  'greedy': self.greedy}

        run_louvain(**params)

        self.runtimes.append(time.time() - start)

    def eval(self, graph_params, method):
        # print("Evaluating task", str(self), 'on graph', graph_params.name, 'with method', method)
        if method not in self.eval_methods:
            raise Exception('method ' + method + ' not found!')
        self.prepare(graph_params, eval=True)

        results_file = self.results_files[0]
        num_of_groups = self.task_params.get('num_of_groups', 3)
        with open(results_file, "r", newline='') as csvfile:
            coms = {}
            datareader = csv.reader(csvfile)
            next(datareader, None)  # skip the headers
            for row in datareader:
                if len(row) != 3:
                    continue
                coms[row[2]] = coms.get(row[2], [])
                coms[row[2]].append(row[1] + '_' + row[0])
            coms = {c: tuple(sorted(nodes)) for c, nodes in coms.items()}

            num_of_communities = max([int(a.split('_')[1]) for b in coms.values() for a in b])
            gt_list = [tuple([str(i) + '_' + str(node) for i in range(num_of_groups)]) for node in
                       range(1, num_of_communities + 1)]
            if graph_params.gt:
                with open(graph_params.gt, "r", newline='') as csvfile:
                    file_data = list(csv.reader(csvfile))
                    gt_list = [tuple([str(i) + '_' + node for i, node in enumerate(row)]) for row in file_data]
            # gt = {a: b for a, b in gt_list}

            scores = []
            # avg between all the groups that have a full match (for example only [0_22, 1_22, 2_22])
            if method == 'full_avg_acc':
                for c, nodes in coms.items():
                    if nodes in gt_list:
                        scores.append(1)
                    elif len(nodes) == num_of_groups:
                        scores.append(0)
                score = np.mean(scores)
            # avg between all the groups (for example [0_22, 1_22, 2_22], [0_22, 2_22])
            elif method == 'all_avg_acc':
                for c, nodes in coms.items():
                    if nodes in gt_list:
                        scores.append(1)
                    else:
                        scores.append(0)
                score = np.mean(scores)
            elif method == 'f1_score':
                pred = list(coms.values())
                all = set(gt_list + pred)
                y_true = [int(a in gt_list) for a in all]
                y_pred = [int(a in pred) for a in all]
                precision, recall = precision_score(y_true, y_pred), recall_score(y_true, y_pred)
                score = f1_score(y_true, y_pred)
            elif method == 'fixed_f1_score':
                pred = []
                graph = MultipartiteLol()
                graph.convert_with_csv(graph_params.files, graph_params.from_to_ids)
                graph.set_nodes_type_dict()
                edges = [tuple(edge[:2]) for edge in graph.edges()]
                y_true, y_pred = [], []
                for i, edge in enumerate(edges):

                    if (i+1)%100000 == 0:
                        print(f"{i+1}/{len(edges)} edges")
                    if int(edge[0][0]) > int(edge[1][0]):
                        continue
                    edge_in_pred = 0
                    for com in list(coms.values()):
                        if edge[0] in com and edge[1] in com:
                            edge_in_pred = 1
                            break
                    if edge_in_pred:
                        pred.append(edge)
                all = set(gt_list + pred)
                y_true = [int(a in gt_list) for a in all]
                y_pred = [int(a in pred) for a in all]
                # for com in gt_list:
                #     if edge[0] in com and edge[1] in com:  # set(edge).issubset(set(com)):
                #         edge_in_gs = 1
                #         break
                #     y_true.append(edge_in_gs)
                score = f1_score(y_true, y_pred)
            else:
                raise Exception('method ' + method + ' not found!')
        # else:
        #     with open(graph_params.gt, "r", newline='') as csvfile:
        #         gt = list(csv.reader(csvfile))
        #         print()
        #     score = 0
        self.scores.append(round(score, 3))

    def get_results_files(self, graph_params, eval=False):
        if not eval:
            return [SEP.join([self.results_dir, os.path.basename(self.results_dir)]) + '.csv']
        else:
            return [SEP.join([self.results_dir, file_name]) for file_name in os.listdir(self.results_dir) if
                    'gt.csv' not in file_name]

    def __str__(self):
        return '2_MultipartiteCommunityDetection'


class MultipartiteGreedyTask(MultipartiteCommunityDetectionTask):
    """
    This is the second task in MAGNET, using a greedy method (also called here task_6).
    This is the Multipartite Community Detection method, using code from MultipartiteCommunityDetection dir.
    This gets data from Results/task_1, and output results to Results/task_6 .
    """
    def __init__(self, results_root='.', task_params=None):
        super().__init__(results_root, task_params)
        self.greedy = True
    def __str__(self):
        return '6_MultipartiteGreedy'

class PathwayProbabilitiesCalculationTask(Task):
    """
    This is the third task in MAGNET (also called here task_3).
    This is the Pathway Probabilities Calculation method, using code from PathwayProbabilitiesCalculation/pathway_probabilities_calculation.py file.
    This gets data from Results/task_1, and output results to Results/task_3 .
    """
    def __init__(self, results_root='.', task_params=None):
        super().__init__(results_root, task_params)
        self.use_task_1_results = True
        self.eval_methods = ['avg_acc', 'norm_avg_acc', 'winner_acc', 'top5_acc', 'f1_score']

    def run(self, graph_params):
        start = time.time()
        print("Running task", str(self), 'on graph', graph_params.name)
        self.prepare(graph_params)

        results_file = self.results_files[0]
        open(results_file, 'w').close()
        list_of_list_graph = MultipartiteLol()
        list_of_list_graph.convert_with_csv(graph_params.files, graph_params.from_to_ids)
        list_of_list_graph.set_nodes_type_dict()
        nodes = list_of_list_graph.nodes()
        starting_points = self.task_params.get('starting_points', 999999999999999999999999999)
        limit_of_steps = self.task_params.get('limit_of_steps', 4)
        if starting_points > len(nodes):
            starting_points = len(nodes)
        sampled_nodes = sample(nodes, starting_points)
        for start_point in sampled_nodes:
            probs = iterate_by_layers(list_of_list_graph, limit_of_steps, start_point)
            passway_probability = normalize_probs_matrix(probs)
            top5_probs_to_csv(passway_probability, results_file, start_point)

        self.runtimes.append(time.time() - start)

    def eval(self, graph_params, method):
        # print("Evaluating task", str(self), 'on graph', graph_params.name, 'with method', method)
        if method not in self.eval_methods:
            raise Exception('method ' + method + ' not found!')
        self.prepare(graph_params, eval=True)

        results_file = self.results_files[0]
        f1_threshold = self.task_params.get('f1_threshold', 0)
        with open(results_file, "r", newline='') as csvfile:
            all_probs = {}
            datareader = csv.reader(csvfile)
            next(datareader, None)  # skip the headers
            for source in datareader:
                source = source[0]
                group = source.split('_')[0]
                neighbors = next(datareader)[1:]
                neighbors_probs = next(datareader)[1:]
                all_probs[source] = all_probs.get(source, {})
                for neighbor, prob in zip(neighbors, neighbors_probs):
                    neighbor_group, neighbor = neighbor.split('_')
                    if neighbor_group != group:
                        all_probs[source][neighbor_group] = all_probs[source].get(neighbor_group, {})
                        all_probs[source][neighbor_group][neighbor] = float(prob)
            bipartite_scores = []
            for from_id, to_id in graph_params.from_to_ids:
                probs = {node.split('_')[1]: neighbors[str(to_id)] for node, neighbors in all_probs.items() if
                         node.split('_')[0] == str(from_id)}
                gt_list = [(i, i) for i in probs.keys()]
                if graph_params.gt:
                    with open(graph_params.gt, "r", newline='') as csvfile:
                        file_data = list(csv.reader(csvfile))
                        gt_list = [(row[from_id], row[to_id]) for row in file_data]
                gt = {a: b for a, b in gt_list}

                if method == 'avg_acc':
                    scores = [neighbors.get(gt.get(node, '-1'), 0) for node, neighbors in probs.items()]
                    score = np.mean(scores)
                elif method == 'norm_avg_acc':
                    scores = [
                        neighbors.get(gt.get(node, '-1'), 0) / sum(neighbors.values()) if sum(neighbors.values()) else 0
                        for node, neighbors in probs.items()]
                    score = np.mean(scores)
                elif method == 'winner_acc':
                    scores = [1 if gt.get(node, '-1') == list(neighbors.keys())[0] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'top5_acc':
                    scores = [1 if gt.get(node, '-1') in list(neighbors.keys())[:5] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'f1_score':
                    # pred_test = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items()]
                    pred = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items() if
                            list(neighbors.values())[0] > f1_threshold]
                    all = set(gt_list + pred)
                    y_true = [int(a in gt_list) for a in all]
                    y_pred = [int(a in pred) for a in all]
                    score = f1_score(y_true, y_pred)
                else:
                    raise Exception('method ' + method + ' not found!')
                bipartite_scores.append(score)
        final_score = round(np.mean(bipartite_scores), 3)
        self.scores.append(final_score)

    def get_results_files(self, graph_params, eval=False):
        if not eval:
            return [SEP.join([self.results_dir, os.path.basename(self.results_dir)]) + '.csv']
        else:
            return [SEP.join([self.results_dir, file_name]) for file_name in os.listdir(self.results_dir) if
                    'gt.csv' not in file_name]

    def __str__(self):
        return '3_PathwayProbabilitiesCalculation'


class ProbabilitiesUsingEmbeddingsTask(Task):
    """
    This is a task that is NOT (as of now) in MAGNET paper (also called here task_4).
    This is using code from PathwayProbabilitiesCalculation/probabilities_using_embeddings.py file.
    This gets data from Results/task_1, and output results to Results/task_4 .
    """
    def __init__(self, results_root='.', task_params=None):
        super().__init__(results_root, task_params)
        self.use_task_1_results = True
        self.eval_methods = ['avg_acc', 'norm_avg_acc', 'winner_acc', 'top5_acc', 'f1_score']

    def run(self, graph_params):
        start = time.time()
        print("Running task", str(self), 'on graph', graph_params.name)
        self.prepare(graph_params)

        results_file = self.results_files[0]
        embedding = self.task_params.get('embedding', 'node2vec')
        epsilon = self.task_params.get('epsilon', 0.1)
        num_of_groups = self.task_params.get('num_of_groups', 3)

        open(results_file, 'w').close()
        distance_functions = [fun_3]  # [fun_1, fun_2, fun_3, fun_4]
        acc_dict = {fun: [] for fun in distance_functions}
        index_count = [0] * 6
        # print(directory)
        if embedding == 'ogre':
            z, graph, initial_size, list_initial_proj_nodes = ogre_static_embeddings(graph_params.files,
                                                                                     graph_params.from_to_ids, epsilon)
            node_to_embed = z['OGRE + node2vec'].list_dicts_embedding[0]
            # node_to_embed = z['node2vec'][1]
        elif embedding == 'node2vec':
            try:
                node_to_embed, graph = node2vec_embed(graph_params.files, graph_params.from_to_ids)
            except:
                raise Exception("node2vec crashed...")
        else:
            raise Exception("embedding " + str(embedding) + " was not found")
        tree, dic = createKD(node_to_embed)
        for idx, node in dic.items():
            identity = node.split("_")[1]
            k = 11
            closest_neighbors, counts = get_closest_neighbors(tree, node, k, node_to_embed, dic, num_of_groups)
            while min(counts.values()) < 5:
                k += 10
                closest_neighbors, counts = get_closest_neighbors(tree, node, k, node_to_embed, dic, num_of_groups)
            # print("Node:",node)
            probs = {}
            for group, nodes in closest_neighbors.items():
                # if identity not in nodes.keys():
                #     index = 5
                # else:
                #     index = list(nodes.keys()).index(identity)
                # index_count[index] += 1
                # print("Found in the index:",index)
                for fun in distance_functions:
                    nodes_after_fun = {node: fun(distance) for node, distance in list(nodes.items())[:5]}
                    nodes_sum = sum(list(nodes_after_fun.values()))
                    if nodes_sum != 0:
                        distances_after_norm = [i / nodes_sum for i in list(nodes_after_fun.values())]
                    else:
                        distances_after_norm = [1 if i == min(list(nodes.items())[:5]) else 0 for i in
                                                list(nodes.items())[:5]]
                    nodes_after_norm = {node: prob for node, prob in zip(nodes_after_fun.keys(), distances_after_norm)}
                    # prob = nodes_after_norm.get(identity, 0)
                    # acc_dict[fun].append(prob)
                probs[group] = nodes_after_norm
                # print("function 3 got acc", prob)
            top5_probs_to_csv(probs, results_file, node)

        self.runtimes.append(time.time() - start)

    def eval(self, graph_params, method):
        # print("Evaluating task", str(self), 'on graph', graph_params.name, 'with method', method)
        if method not in self.eval_methods:
            raise Exception('method ' + method + ' not found!')
        self.prepare(graph_params, eval=True)

        results_file = self.results_files[0]
        f1_threshold = self.task_params.get('f1_threshold', 0)
        with open(results_file, "r", newline='') as csvfile:
            all_probs = {}
            datareader = csv.reader(csvfile)
            next(datareader, None)  # skip the headers
            for source in datareader:
                source = source[0]
                group = source.split('_')[0]
                neighbors = next(datareader)[1:]
                neighbors_probs = next(datareader)[1:]
                all_probs[source] = all_probs.get(source, {})
                for neighbor, prob in zip(neighbors, neighbors_probs):
                    neighbor_group, neighbor = neighbor.split('_')
                    if neighbor_group != group:
                        all_probs[source][neighbor_group] = all_probs[source].get(neighbor_group, {})
                        all_probs[source][neighbor_group][neighbor] = float(prob)
            bipartite_scores = []
            for from_id, to_id in graph_params.from_to_ids:
                probs = {node.split('_')[1]: neighbors[str(to_id)] for node, neighbors in all_probs.items() if
                         node.split('_')[0] == str(from_id)}
                gt_list = [(i, i) for i in probs.keys()]
                if graph_params.gt:
                    with open(graph_params.gt, "r", newline='') as csvfile:
                        file_data = list(csv.reader(csvfile))
                        gt_list = [(row[from_id], row[to_id]) for row in file_data]
                gt = {a: b for a, b in gt_list}

                if method == 'avg_acc':
                    scores = [neighbors.get(gt.get(node, '-1'), 0) for node, neighbors in probs.items()]
                    score = np.mean(scores)
                elif method == 'norm_avg_acc':
                    scores = [
                        neighbors.get(gt.get(node, '-1'), 0) / sum(neighbors.values()) if sum(neighbors.values()) else 0
                        for node, neighbors in probs.items()]
                    score = np.mean(scores)
                elif method == 'winner_acc':
                    scores = [1 if gt.get(node, '-1') == list(neighbors.keys())[0] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'top5_acc':
                    scores = [1 if gt.get(node, '-1') in list(neighbors.keys())[:5] else 0 for node, neighbors in
                              probs.items()]
                    score = np.mean(scores)
                elif method == 'f1_score':
                    # pred_test = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items()]
                    pred = [(node, list(neighbors.keys())[0]) for node, neighbors in probs.items() if
                            list(neighbors.values())[0] > f1_threshold]
                    all = set(gt_list + pred)
                    y_true = [int(a in gt_list) for a in all]
                    y_pred = [int(a in pred) for a in all]
                    score = f1_score(y_true, y_pred)
                else:
                    raise Exception('method ' + method + ' not found!')
                bipartite_scores.append(score)
        final_score = round(np.mean(bipartite_scores), 3)
        self.scores.append(final_score)

    def get_results_files(self, graph_params, eval=False):
        if not eval:
            return [SEP.join([self.results_dir, os.path.basename(self.results_dir)]) + '.csv']
        else:
            return [SEP.join([self.results_dir, file_name]) for file_name in os.listdir(self.results_dir) if
                    'gt.csv' not in file_name]

    def __str__(self):
        return '4_ProbabilitiesUsingEmbeddings'
