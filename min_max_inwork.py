import sys
from heapq import heappush, heappop
from collections import defaultdict
import json
import plotly.graph_objects as go
import networkx as nx




class Task:
    def __init__(self, source, target, blocks, numrisorse):
        self.source = source
        self.target = target
        self.blocks = blocks
        self.numrisorse = numrisorse

    def __repr__(self):
        return f"Task({self.source} -> {self.target}, weight={self.weight}, numrisorse={self.numrisorse})"

class Worker:
    def __init__(self, worker_id, available_blocks):
        self.worker_id = worker_id
        self.available_blocks = available_blocks
        self.working_on_task = None

    def assign_task(self, task: Task):
        self.working_on_task = task

    def __repr__(self):
        task_info = f"working on {self.working_on_task.target}" if self.working_on_task else ''
        return f"Worker(id={self.worker_id}, available_blocks={self.available_blocks}, {task_info})"


def any_worker_working(workers):
    return any(worker.working_on_task is not None for worker in workers)

def get_in_work_nodes(workers):
    return [worker.working_on_task.target for worker in workers if worker.working_on_task is not None]



def load_digraph_from_file(filename: str):
    with open(filename, "r") as f:
        data = json.load(f)
    print(data)

    # Initialize directed graph
    G = nx.DiGraph()

    # Add nodes with attributes (e.g., x and y)
    for node in data["nodes"]:
        G.add_node(node["id"], x=node["x"], y=node["y"])

    # Add edges with weights
    for edge in data["edges"]:
        G.add_edge(edge["source"], edge["target"], weight=edge["weight"], numrisorse=edge["numrisorse"]) 

    # Example: print nodes and edges
    print("Nodes with attributes:")
    print(G.nodes(data=True))

    print("\nEdges with weights:")
    print(G.edges(data=True))
    
    return G


def get_visitable_edges(G, start_edges, visited_nodes):
    visitable = []
    start_nodes = [edge[1] for edge in start_edges]
    for node in start_nodes:
        if G.out_degree(node) > 0:
            for neighbor in G.successors(node):
                if neighbor not in visited_nodes and neighbor not in visitable and neighbor != 'End':
                    visitable.append((node, neighbor))
    return visitable


def log(msg):
    print(msg)


def get_next_visitable_edge_min_weight(G, visited_nodes, available_blocks_worker):
    min_weight_edge = None
    min_weight = float('inf')
    for edge in G.edges(data=True):
        if edge[0] in visited_nodes and edge[1] not in visited_nodes:
            if edge[2]['weight'] <= available_blocks_worker:
                if edge[2]['weight'] < min_weight:
                    min_weight = edge[2]['weight']
                    min_weight_edge = (edge[0], edge[1])
    return min_weight_edge

def get_next_visitable_edge_max_weight(G, visited_nodes, available_blocks_worker):
    max_weight_edge = None
    max_weight = -999
    for edge in G.edges(data=True):
        if edge[0] in visited_nodes and edge[1] not in visited_nodes:
            if edge[2]['weight'] <= available_blocks_worker:
                if edge[2]['weight'] > max_weight:
                    max_weight = edge[2]['weight']
                    max_weight_edge = (edge[0], edge[1])
    return max_weight_edge

def get_visitable_edge_first_available(G, visited_nodes, available_blocks_worker):
    for edge in G.edges(data=True):
        if edge[0] in visited_nodes and edge[1] not in visited_nodes and edge[2]['weight'] <= available_blocks_worker:
            return (edge[0], edge[1])
    return None

def get_next_visitable_edge_heuristic(G, visited_nodes, available_blocks_worker):
    best_edge = None
    best_score = float('inf')
    for edge in G.edges(data=True):
        if edge[0] in visited_nodes and edge[1] not in visited_nodes:
            edge_weight = edge[2]['weight']
            remaining_resources = available_blocks_worker - edge_weight
            outgoing_edges = G.out_degree(edge[1])
            # Heuristic score calculation
            # Lower weight and more outgoing edges are preferred
            score = edge_weight - (0.5 * outgoing_edges)
            if remaining_resources >= 0 and score < best_score:
                best_score = score
                best_edge = (edge[0], edge[1])
    return best_edge

def get_next_visitable_edge(G, visited_nodes, available_blocks_worker):
    #return get_next_visitable_edge_heuristic(G, visited_nodes, available_blocks_worker)
    #return get_visitable_edge_first_available(G, visited_nodes, available_blocks_worker)
    return get_next_visitable_edge_min_weight(G, visited_nodes, available_blocks_worker)
    #return get_next_visitable_edge_max_weight(G, visited_nodes, available_blocks_worker)




def minmax_from_file(filename: str, takt=2, resources_per_shift=[2,2,0]):
    day_blocks = 8 * 60 / 10
    pause = (30 + 40) / 10
    day_blocks = day_blocks - pause
    
    G = load_digraph_from_file(filename)
    visited_nodes = [node for node in G.nodes if G.in_degree(node) == 0]
    visited_nodes.append('End')
    currently_visiting_nodes = []

    log("-------- edge list ----------")
    for edge in G.edges(data=True):
        if edge[1] not in visited_nodes:
            log(f"  {edge[0]} -> {edge[1]}, weight: {edge[2]['weight']}, numrisorse: {edge[2]['numrisorse']}")
    log("-------- edge list end ----------")

    log("-------- start graph visit ----------")
    for day in range(takt):
        log(f"Day {day + 1} / {takt}")
        for shift in range(len(resources_per_shift)):
            log(f"  Shift {shift + 1} / {len(resources_per_shift)}")
            numresources = resources_per_shift[shift]
            log(f"    {numresources} resources")
            workers = [Worker(i, int(day_blocks)) for i in range(numresources)]
            [log(f"    {worker}") for worker in workers]
            [worker.assign_task(Task("dummy", "dummy", 0, 0)) for worker in workers]
            while any_worker_working(workers):
                log("...... working ......")
                [worker.assign_task(None) for worker in workers]
            # while  not all_workers_idle:
            #     for worker in range(numresources):
            #         edge_to_visit = get_next_visitable_edge(G, visited_nodes, available_blocks[worker])
            #             task = Task(edge_to_visit[0], edge_to_visit[1], G[edge_to_visit[0]][edge_to_visit[1]]['weight'], G[edge_to_visit[0]][edge_to_visit[1]]['numrisorse'])

            # num_of_visit_in_this_loop = 1
            # while num_of_visit_in_this_loop > 0:
            #     num_of_visit_in_this_loop = 0
            #     for worker in range(numresources):
            #         # note: how do we choose the next task to be executed
            #         edge_to_visit = get_next_visitable_edge(G, visited_nodes, available_blocks[worker])
            #         if edge_to_visit:
            #             edge_weight = G[edge_to_visit[0]][edge_to_visit[1]]['weight']
            #             edge_numrisorse = G[edge_to_visit[0]][edge_to_visit[1]]['numrisorse']
            #             available_blocks[worker] -= edge_weight
            #             # this edge is visited by 1 resource
            #             G[edge_to_visit[0]][edge_to_visit[1]]['numrisorse'] -= 1
            #             log(f"      (worker {worker} blocks {available_blocks[worker]+edge_weight} -> {available_blocks[worker]}) works on ({edge_to_visit[1]}, weight {edge_weight} numrisorse {edge_numrisorse} -> {G[edge_to_visit[0]][edge_to_visit[1]]['numrisorse']})")
            #             if G[edge_to_visit[0]][edge_to_visit[1]]['numrisorse'] <= 0:
            #                 # node completely visited, all needed resourcses are used
            #                 visited_nodes.append(edge_to_visit[1])
            #             num_of_visit_in_this_loop += 1
            #         else:
            #             # worker cannot do anything else in this shift
            #             log(f"      (worker {worker} blocks {available_blocks[worker]}) has no visitable edges")
    log("-------- end graph visit ----------")

    if len(visited_nodes) == G.number_of_nodes():
        log("All nodes visited")
    else:
        log(f"Not all nodes visited, remaining:")
    # for edge in G.edges(data=True):
    #     if edge[1] not in visited_nodes:
    #         log(f"  {edge[0]} -> {edge[1]}, weight: {edge[2]['weight']}, remaining numrisorse: {edge[2]['numrisorse']}")




def minmax_from_file_v1(filename: str):
    G = load_digraph_from_file(filename)

    numresources = 2
    takt = 2
    total_nodes_num = G.number_of_nodes()

    day_blocks = 8 * 60 / 10
    takt_blocks = takt * day_blocks
    
    print("-------- start graph visit ----------")
    visited_nodes = []
    visitable_edges = [('', 'Start')]
    while len(visitable_edges) > 0:
        visitable_edges = get_visitable_edges(G, visitable_edges, visited_nodes)
        visitable_nodes = [edge[1] for edge in visitable_edges]
        print("Visitable nodes: ", visitable_nodes)
        
        available_blocks = numresources * day_blocks
        for edge in visitable_edges:
            edge_weight = G[edge[0]][edge[1]]['weight']
            if available_blocks >= edge_weight:
                # we can visit the node in this shift
                available_blocks -= edge_weight
                visited_nodes.append(edge[1])
                print(f"  Visiting {edge[0]} to {edge[1]}, remaining blocks: {available_blocks}")

    print("-------- end graph visit ----------")












def visualize_from_file(filename: str):
    with open(filename, "r") as f:
        data = json.load(f)
    
    # Edge trace
    edge_x, edge_y = [], []
    for edge in data["edges"]:
        # Fetch source node coordinates
        source_node = next(node for node in data["nodes"] if node["id"] == edge["source"])
        x0, y0 = source_node["x"], source_node["y"]
        
        # Fetch target node coordinates
        target_node = next(node for node in data["nodes"] if node["id"] == edge["target"])
        x1, y1 = target_node["x"], target_node["y"]
        
        # Add edge coordinates
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
    
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=0.5, color="#888"),
        hoverinfo="none",
        mode="lines"
    )
    
    # Node trace
    node_x = [node["x"] for node in data["nodes"]]
    node_y = [node["y"] for node in data["nodes"]]
    node_text = [node["id"] for node in data["nodes"]]
    
    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="bottom center",
        marker=dict(
            color="lightblue",
            size=15,
            line=dict(width=2, color="DarkSlateGrey")
        )
    )
    
    # Create figure
    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.show()



       


def minimize_max_tokens(petri_net, start_node, end_node, max_passages):
    # Same function as above, just copied for completeness
    queue = [(1, 1, start_node, [start_node], 0)]
    best_solutions = {}
    best_solutions[(start_node, frozenset([start_node]))] = 1
    best_path = None
    min_max_tokens = float('inf')
    
    while queue:
        max_tokens_so_far, current_tokens, node, path, passages_used = heappop(queue)
        
        if max_tokens_so_far >= min_max_tokens or passages_used > max_passages:
            continue
        
        # Added debugging
        print(f"Exploring: node={node}, tokens={current_tokens}, max={max_tokens_so_far}, path={path}")
        
        if node == end_node and len(set(path)) >= len(petri_net) - 1:  # -1 because End might not be counted yet
            min_max_tokens = max_tokens_so_far
            best_path = path
            print(f"Found solution: {path} with max tokens: {max_tokens_so_far}")
            continue
            
        if node == end_node:
            print(f"Reached end but only visited {len(set(path))} nodes out of {len(petri_net)}")
            continue
        
        for neighbor, token_multiplier in petri_net[node]:
            if neighbor in path and neighbor != end_node:
                continue
                
            new_tokens = current_tokens * token_multiplier
            new_max_tokens = max(max_tokens_so_far, new_tokens)
            new_path = path + [neighbor]
            new_passages = passages_used + 1
            
            state = (neighbor, frozenset(new_path))
            
            if state not in best_solutions or new_max_tokens < best_solutions[state]:
                best_solutions[state] = new_max_tokens
                heappush(queue, (new_max_tokens, new_tokens, neighbor, new_path, new_passages))
    
    return min_max_tokens, best_path

# Simpler example
simple_net = {
    'Start': [('A', 1)],
    'A': [('B', 2), ('C', 3)],
    'B': [('End', 1)],
    'C': [('End', 2)],
    'End': []
}

# print("Testing with simple network:")
# min_tokens, optimal_path = minimize_max_tokens(simple_net, 'Start', 'End', 3)
# print(f"\nFinal result - Minimum maximum tokens: {min_tokens}")
# print(f"Optimal path: {' -> '.join(optimal_path)}")



if len(sys.argv) >= 5:
    takt = int(sys.argv[1])
    shifts = [int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])]
else:
    takt = 2  # Default value for takt
    shifts = [3, 3, 0]  # Default values for shifts

print(f"takt={takt}, shifts={shifts}")

#visualize_from_file(filename="logs\merged_graph_data_splitted_operations.json")

#minmax_from_file(filename="logs\merged_graph_data.json", takt=2, resources_per_shift=[9,9,0])
minmax_from_file(filename="logs\merged_graph_data_splitted_operations.json", takt=takt, resources_per_shift=shifts)

