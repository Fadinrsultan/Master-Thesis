# ── US-GAAP 2025: Presentation Forest → Highlighted Paths (Fast, No Hang)
# Draws ONLY the root→metric paths for a chosen role. Avoids heavy layouts.
# Reqs: arelle, networkx, pyvis
#
# References:
# - Arelle (XBRL engine): https://arelle.org/
# - FASB US-GAAP Taxonomy: https://fasb.org/xbrl
# - PyVis docs: https://pyvis.readthedocs.io/

from collections import defaultdict, deque
from arelle import Cntlr, XbrlConst
from pyvis.network import Network
import networkx as nx
import pathlib, webbrowser, os

# ───────────────────────────────────────────────────────────────────────────────
# CONFIG
ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"

# Choose a role to visualize
# Examples:
#   "http://fasb.org/us-gaap/role/statement/StatementOfIncome"
#   "http://fasb.org/us-gaap/role/statement/StatementOfFinancialPositionClassified"
#   "http://fasb.org/us-gaap/role/statement/StatementOfCashFlowsIndirect"
role_uri = "http://fasb.org/us-gaap/role/statement/StatementOfIncomeInterestBasedRevenue"

# Output
out_file = "/Users/fadisultan/Downloads/soi_network.html"

# Target metrics (by local qname part). "FreeCashFlow" is derived and likely absent.
METRICS = [
    "Revenues",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "OperatingIncomeLoss",
    "GrossProfit",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "LongTermDebt",
    "ShortTermInvestments",
    "CostOfRevenue",
    "OperatingExpenses",
    "IncomeTaxExpenseBenefit",
    "AccountsReceivableNetCurrent",
    "FreeCashFlow",
]

# ───────────────────────────────────────────────────────────────────────────────
# LOAD + RELATIONSHIPS
cntlr = Cntlr.Cntlr()
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)
pres = model_xbrl.relationshipSet(XbrlConst.parentChild)

# Enumerate roles
roles = {rel.linkrole for rel in pres.modelRelationships}
print("presentation networks:", len(roles))

def roots_for_role(role_uri_):
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri_:
            parents.add(rel.fromModelObject)
            children.add(rel.toModelObject)
    return list(parents - children)

def _best_label(concept):
    return concept.label(lang="en") or concept.label(lang="en-US") or str(concept.qname)

# ───────────────────────────────────────────────────────────────────────────────
# BUILD FOREST (role → list of root node dicts)

forest = defaultdict(list)
for role in roles:
    roots = roots_for_role(role)
    nodes = {c: {"id": str(c.qname), "label": _best_label(c), "children": []} for c in roots}
    q = deque(roots)
    while q:
        parent = q.popleft()
        for rel in pres.fromModelObject(parent):
            if rel.linkrole != role:
                continue
            child = rel.toModelObject
            if child not in nodes:
                nodes[child] = {"id": str(child.qname), "label": _best_label(child), "children": []}
            nodes[parent]["children"].append(nodes[child])
            q.append(child)
    forest[role] = [nodes[r] for r in roots]

print("forest built with",
      sum(len(v) for v in forest.values()), "top-level nodes across",
      len(forest), "networks")

# ───────────────────────────────────────────────────────────────────────────────
# PATH FINDING (root→metric), PRUNED SUBGRAPH ONLY

def _node_matches_metric(node, metric_name: str) -> bool:
    qname = node.get("id", "")
    local = qname.split(":", 1)[-1] if ":" in qname else qname
    return local == metric_name or node.get("label", "") == metric_name

def _dfs_paths_from_root(root_node, metric_set):
    """
    Returns:
      - paths_by_metric: metric -> list of (u_id, v_id) edges along root→target path
      - nodes_on_paths: set of node_ids that lie on any returned path
    """
    paths_by_metric = {}
    nodes_on_paths = set()

    stack = [(root_node, [])]  # (node_dict, path_node_ids)
    while stack:
        node, path_ids = stack.pop()
        node_id = node["id"]
        new_path_ids = path_ids + [node_id]

        # if this node is a target metric, record the path (first found wins)
        for m in metric_set:
            if m not in paths_by_metric and _node_matches_metric(node, m):
                edge_path = [(new_path_ids[i], new_path_ids[i+1]) for i in range(len(new_path_ids)-1)]
                paths_by_metric[m] = edge_path
                for nid in new_path_ids:
                    nodes_on_paths.add(nid)

        for ch in node.get("children", []):
            stack.append((ch, new_path_ids))

    return paths_by_metric, nodes_on_paths

def collect_pruned_graph(forest, role_uri_, metrics):
    """
    Builds a subgraph that is the union of all root→metric paths (no extra branches).
    Returns:
      - nodes_map: id -> label (ONLY nodes on any path)
      - edges_map: set of (u,v) edges (ONLY edges on any path)
      - highlight_edges: (u,v) -> {'color', 'width'} for styling per metric
      - found_metrics, missing_metrics
      - target_ids: set of node ids that are metric endpoints
    """
    if role_uri_ not in forest:
        raise ValueError(f"role not found → {role_uri_}")

    metrics_ordered = list(metrics)
    metric_set = set(metrics_ordered)

    # palette for paths
    palette = [
        "#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
        "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62"
    ]

    # 1) Find paths from each root
    found_paths = {}     # metric -> list[(u,v)]
    nodes_on_paths = set()
    nodes_map_full = {}  # id -> label (for nodes we actually see while traversing)

    # register all node labels we might need (but we'll prune later)
    stack = [n for r in forest[role_uri_] for n in [r]]
    while stack:
        n = stack.pop()
        nodes_map_full[n["id"]] = n.get("label", n["id"])
        stack.extend(n.get("children", []))

    for root in forest[role_uri_]:
        p_by_m, nodes_set = _dfs_paths_from_root(root, metric_set)
        # Merge if metric not already found (prefer first path discovered)
        for m, p in p_by_m.items():
            if m not in found_paths:
                found_paths[m] = p
        nodes_on_paths |= nodes_set

    # 2) Build pruned node/edge sets (only nodes/edges on any metric path)
    edges_map = set()
    for path in found_paths.values():
        for e in path:
            edges_map.add(e)
            nodes_on_paths.add(e[0])
            nodes_on_paths.add(e[1])

    nodes_map = {nid: nodes_map_full[nid] for nid in nodes_on_paths if nid in nodes_map_full}

    # 3) Styling for highlight edges
    highlight_edges = {}
    found_metrics, missing_metrics = [], []
    target_ids = set()

    for i, m in enumerate(metrics_ordered):
        path = found_paths.get(m)
        if not path:
            missing_metrics.append(m)
            continue
        found_metrics.append(m)
        color = palette[i % len(palette)]
        for e in path:
            highlight_edges[e] = {"color": color, "width": 4}

        # endpoint for node styling: last 'v' in the path, or root if empty
        if path:
            target_ids.add(path[-1][1])

    return nodes_map, edges_map, highlight_edges, found_metrics, missing_metrics, target_ids

# ───────────────────────────────────────────────────────────────────────────────
# RENDER (PyVis) — pruned subgraph only

def show_pruned_network(forest, role_uri_, metrics, html_path):
    nodes_map, edges_map, highlight_edges, found_metrics, missing_metrics, target_ids = collect_pruned_graph(
        forest, role_uri_, metrics
    )

    # Build NetworkX graph (only nodes/edges we need)
    G = nx.DiGraph()
    for nid, label in nodes_map.items():
        node_kwargs = {"label": label, "title": nid, "shape": "dot", "size": 12}
        if nid in target_ids:
            node_kwargs["size"] = 18
            node_kwargs["borderWidth"] = 3
        G.add_node(nid, **node_kwargs)

    for (u, v) in edges_map:
        attrs = {"arrows": "to", "smooth": True}
        if (u, v) in highlight_edges:
            attrs.update(highlight_edges[(u, v)])
        else:
            attrs.update({"color": "#cfcfcf", "width": 1})
        G.add_edge(u, v, **attrs)

    net = Network(height="900px", width="100%", directed=True, bgcolor="#ffffff")
    net.from_nx(G)

    # Start with physics OFF to avoid any chance of hanging. You can enable from the UI.
    try:
        net.show_buttons(filter_=['physics'])
    except Exception:
        pass

    net.set_options(r"""{
      "physics": {
        "enabled": false,
        "solver": "barnesHut",
        "barnesHut": {
          "gravitationalConstant": -2000,
          "springLength": 120,
          "springConstant": 0.05
        },
        "stabilization": { "iterations": 150 }
      },
      "edges": {
        "arrows": { "to": { "enabled": true } },
        "smooth": true
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 200
      }
    }""")

    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    net.write_html(html_path)
    webbrowser.open_new_tab(pathlib.Path(html_path).as_uri())
    print("HTML written and opened →", html_path)

    if found_metrics:
        print("Highlighted metrics:", ", ".join(found_metrics))
    if missing_metrics:
        print("Not found in this role (skipped):", ", ".join(missing_metrics))

# ───────────────────────────────────────────────────────────────────────────────
# RUN
show_pruned_network(forest, role_uri, METRICS, out_file)
