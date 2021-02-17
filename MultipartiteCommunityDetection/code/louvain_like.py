import numpy as np
import networkx as nx
from MultipartiteCommunityDetection.code.status_directed import Status

__MIN = 0.0000001


def partition_at_level(dendrogram, level):
    """
    Create a dictionary of the partition at a specific level of the dendrogram (i.e. of the algorithm).
    :param dendrogram: The dendrogram, a list of the partitions during the algorithm.
           The passing from one element of the list to another involves a building of a graph induced by the previous
           partition.
    :param level: The level in the dendrogram by which we will build the partition.
    :return: The partition: {node: community}
    """
    partition = dendrogram[0].copy()
    for index in range(1, level + 1):
        for node, community in partition.items():
            partition[node] = dendrogram[index][community]
    return partition


def best_partition(graph, partition=None, weight='weight', nodetype='type', resolution=1., beta_penalty=None):
    """
    Compute a partition of the graph's nodes which is a local maximum of the modularity using the Louvain heuristics.
    This is the partition of highest modularity, i.e. the highest partition of the dendrogram generated by the
    Louvain algorithm.

    :param graph: NetworkX graph.
    The graph to be decomposed.
    :param partition: dict, optional.
    If given, this dictionary {node: community} will be the starting point of the algorithm.
    :param weight: str, optional.
    The code will look for edges' attributes with this name and use this attribute as the edge weights (floats).
    Default to 'weight'.
    :param nodetype: str, optional.
    The code will use the nodes' attributes with this name and use this attribute as the type of nodes.
    Default to 'type'.
    NOTE: the nodes should have attributes given as lists, each of which represents an indicator list to the type of the
    node, for example: a node of type 4 will have the following node attribute: [0, 0, 0, 0, 1, 0, ..., 0]
    :param resolution: float, optional.
    Will change the size of the communities, default to 1. This factor multiplies the second term in the
    modularity function (the product between degrees).
    :param beta_penalty: list, optional.
    A list of length equal to the number of node types. The communities will be penalised for having numbers of vertices
    of the same types in a single community. Default to a list of zeroes, i.e. no such penalty.
    :return: dict.
    The partition {node: community}, with communities numbered from 0 to number of communities
    """
    tree = generate_dendrogram(graph, partition, weight, nodetype, resolution, beta_penalty)
    return partition_at_level(tree, len(tree) - 1)


def generate_dendrogram(graph, part_init=None, weight='weight', nodetype='type', resolution=1., beta_penalty=None):
    """
    Build the dendrogram by the Louvain algorithm and according to our modularity function.
    :param graph: A directed networkx graph.
    :param part_init: Initial partition from which the algorithm can start. Default to None, meaning that the algorithm
           will initialize from one community for each node.
    :param weight: The attribute name of the edge weights in the networkx graph. Default to 'weight'.
    :param nodetype: The attribute name of the node vector of types in the networkx graph. Default to 'type'.
    :param resolution: A hyper-parameter that determines the size of the communities. The larger it is, the smaller the
           sizes of communities will tend to be.
    :param beta_penalty: A list of length equal to the number of node types. The communities will be penalised for
           having numbers of vertices of the same types in a single community.
    :return: The whole dendrogram.
    """
    if not graph.is_directed():
        raise TypeError("Bad graph type, use only directed graph")
    # If there is no edge in the graph, the best partition is every node in its community.
    if graph.number_of_edges() == 0:
        return [{node: i for i, node in enumerate(graph.nodes())}]
    if beta_penalty is None:
        zero_node = list(graph.nodes())[0]
        beta_penalty = [0.] * len(graph.node[zero_node][nodetype])

    current_graph = graph.copy()
    status = Status()
    status.init(current_graph, weight, nodetype, part_init)

    # attrs = vars(status)
    # print("--------------networkx-------------")
    # print(', '.join("%s: %s" % item for item in attrs.items()))
    status_list = []
    __one_level(current_graph, status, weight, nodetype, resolution, beta_penalty)

    # attrs = vars(status)
    # print("--------------networkx-------------")
    # print(', '.join("%s: %s" % item for item in attrs.items()))

    new_mod = __modularity(status, resolution, beta_penalty)
    print(new_mod, "networkx")
    partition = __renumber(status.node2com)
    status_list.append(partition)
    mod = new_mod
    current_graph = induced_graph(partition, current_graph, weight, nodetype)
    status.init(current_graph, weight, nodetype)

    while True:
        __one_level(current_graph, status, weight, nodetype, resolution, beta_penalty)
        new_mod = __modularity(status, resolution, beta_penalty)
        if new_mod - mod < __MIN:
            break
        partition = __renumber(status.node2com)
        status_list.append(partition)
        mod = new_mod
        current_graph = induced_graph(partition, current_graph, weight, nodetype)
        status.init(current_graph, weight, nodetype)
    return status_list[:]


def induced_graph(partition, graph, weight, nodetype):
    """Compute the graph induced by the previous partition - two nodes from the same community will be represented by
    the same node in the resulting graph"""
    ret = nx.DiGraph()
    ret.add_nodes_from(partition.values())
    for node1, node2, datas in graph.edges(data=True):
        edge_weight = datas.get(weight, 1)
        com1 = partition[node1]
        com2 = partition[node2]
        w_prec = ret.get_edge_data(com1, com2, {weight: 0}).get(weight, 1)
        ret.add_edge(com1, com2, **{weight: w_prec + edge_weight})
    for node, data in graph.nodes(data=True):
        com = partition[node]
        com_data = ret.nodes[com]
        if nodetype not in com_data:
            com_data[nodetype] = graph.nodes[node][nodetype]
        else:
            com_data[nodetype] = [exist + add for exist, add in zip(com_data[nodetype], graph.nodes[node][nodetype])]
    return ret


def __renumber(dictionary):
    """Renumber the values of the dictionary (i.e. communities) from 0 to n"""
    count = 0
    ret = dictionary.copy()
    new_values = {}

    for key in dictionary.keys():
        value = dictionary[key]
        new_value = new_values.get(value, -1)
        if new_value == -1:
            new_values[value] = count
            new_value = count
            count += 1
        ret[key] = new_value

    return ret


def __one_level(graph, status, weight_key, nodetype, resolution, beta_penalty):
    # print("graph.adj()", graph.adj)

    """Compute one level of communities"""
    modified = True
    cur_mod = __modularity(status, resolution, beta_penalty)
    # print(cur_mod, "networkx")

    new_mod = cur_mod
    np.random.seed(42)
    while modified:
        cur_mod = new_mod
        modified = False
        nodes_list = list(graph.nodes())

        np.random.shuffle(nodes_list)

        res_over_m = resolution / status.total_weight

        for node in nodes_list:
            com_node = status.node2com[node]
            neigh_com_in, neigh_com_out = __neighcom(node, graph, status, weight_key)
            node_type_vec = np.array(graph.nodes[node][nodetype])
            remove_cost = - (neigh_com_in.get(com_node, 0) + neigh_com_out.get(com_node, 0)) + \
                          ((status.in_degrees.get(com_node, 0.) - status.g_in_degrees.get(node, 0.)) *
                           status.g_out_degrees.get(node, 0) +
                           (status.out_degrees.get(com_node, 0.) - status.g_out_degrees.get(node, 0.)) *
                           status.g_in_degrees.get(node, 0)) * res_over_m + \
                          2 * np.vdot(np.multiply(np.array(status.com_nodes[com_node]) - node_type_vec, node_type_vec),
                                      beta_penalty)
            __remove(node, com_node, neigh_com_in.get(com_node, 0.) + neigh_com_out.get(com_node, 0.), node_type_vec,
                     status)
            best_com = com_node
            best_increase = 0
            all_neigh_com = list(set(neigh_com_in.keys()).union(set(neigh_com_out.keys())))

            np.random.shuffle(all_neigh_com)
            for com in all_neigh_com:
                neigh_in = neigh_com_in.get(com, 0)
                neigh_out = neigh_com_out.get(com, 0)
                incr = remove_cost + neigh_in + neigh_out - \
                       (status.g_in_degrees.get(node, 0) * status.out_degrees.get(com, 0.) +
                        status.g_out_degrees.get(node, 0) * status.in_degrees.get(com, 0.)) * res_over_m - \
                       2 * np.vdot(np.multiply(status.com_nodes[com], node_type_vec), beta_penalty)
                if incr > best_increase:
                    best_increase = incr
                    best_com = com
            __insert(node, best_com, neigh_com_in.get(best_com, 0.) + neigh_com_out.get(best_com, 0.), node_type_vec,
                     status)
            if best_com != com_node:
                modified = True
        new_mod = __modularity(status, resolution, beta_penalty)
        if new_mod - cur_mod < __MIN:
            break


def __neighcom(node, graph, status, weight_key):
    """Compute the communities in the neighborhood of node in the graph given with the decomposition node2com"""
    weights_out = {}
    for neighbor, datas in graph[node].items():
        if neighbor != node:
            edge_weight = datas.get(weight_key, 1)
            out_com = status.node2com[neighbor]
            weights_out[out_com] = weights_out.get(out_com, 0) + edge_weight
    weights_in = {}
    for neighbor in graph.predecessors(node):
        if neighbor != node:
            edge_weight = graph[neighbor][node].get(weight_key, 1)
            in_com = status.node2com[neighbor]
            weights_in[in_com] = weights_out.get(in_com, 0) + edge_weight
    return weights_in, weights_out


def __remove(node, com, weight, node_type, status):
    """Remove node from community com and modify status"""
    status.in_degrees[com] = (status.in_degrees.get(com, 0.) - status.g_in_degrees.get(node, 0.))
    status.out_degrees[com] = (status.out_degrees.get(com, 0.) - status.g_out_degrees.get(node, 0.))
    status.internals[com] = float(status.internals.get(com, 0.) - weight - status.loops.get(node, 0.))
    status.com_nodes[com] = [exist - add for exist, add in zip(status.com_nodes[com], node_type)]
    status.node2com[node] = -1
    status.com_nodes[-1] = list(node_type)


def __insert(node, com, weight, node_type, status):
    """Insert node into community and modify status"""
    status.node2com[node] = com
    status.in_degrees[com] = (status.in_degrees.get(com, 0.) + status.g_in_degrees.get(node, 0.))
    status.out_degrees[com] = (status.out_degrees.get(com, 0.) + status.g_out_degrees.get(node, 0.))
    status.com_nodes[com] = [exist + add for exist, add in zip(status.com_nodes[com], node_type)]
    status.internals[com] = float(status.internals.get(com, 0.) + weight + status.loops.get(node, 0.))
    if com != -1:
        del status.com_nodes[-1]


def __modularity(status, resolution, beta_penalty):
    """
    Compute the modularity of the current partition (status).
    The modularity of the partition in our solution is:
    1 / m *  sum_{i,j} [[A_{ij} - resolution * k^{in}_{i} * k^{out}_{j} / m - beta[S_i, S_j]] * delta(C_i, C_j)]
    where:
    m - the sum of all edge weights in the graph.
    A - the weighted adjacency matrix of the graph.
    k^{in}_{i} (k^{out}, resp.) - the weighted in (out, resp.) degree of a node i.
    S_i - the shape of a node i. If i represents an original node, it has a single type.
          Otherwise, it holds a vector counting the number of nodes of each type held in the vertex.
    beta[S_i, S_j] - the sum over all possible node types, of the corresponding beta penalty for this type, times
                     the product of counts of this type in i and in j.
    delta[C_i, C_j] - Kronecker's delta over the communities of i and j.
    """
    links = float(status.total_weight)
    result = 0.
    for community in set(status.node2com.values()):
        within = status.internals.get(community, 0.)
        in_deg = status.in_degrees.get(community, 0.)
        out_deg = status.out_degrees.get(community, 0.)
        shape_counts = status.com_nodes.get(community, [0] * len(beta_penalty))
        if links > 0:
            result += within / links - resolution * in_deg * out_deg / (links ** 2) - \
                      np.vdot(beta_penalty, np.power(shape_counts, 2)) / links
            # print(result, "networkx")
    return result
