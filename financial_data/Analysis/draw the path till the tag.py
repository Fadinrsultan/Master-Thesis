"""
US-GAAP 2025 — Per-role visualization with root→metric path highlighting.
Metric nodes are ~6× larger (ellipse 'size'), light-green fill, with red path edges.

Output:
  /…/usgaap_role_graphs/
      index.html
      <role>.html

Requires (in your venv):
  pip install arelle-release pyvis
"""

from collections import defaultdict, deque
from pathlib import Path
import html, json, re, sys

from arelle import Cntlr, XbrlConst
from pyvis.network import Network

# ----------------------------
# CONFIG
# ----------------------------
ENTRY_XSD     = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"
OUT_DIR       = "/Users/fadisultan/Downloads/usgaap_role_graphs"
METRIC_SCALE  = 6.0     # ← make metric nodes ~6× larger; spacing scales accordingly
BASE_X_SPACING = 260    # base horizontal spacing between siblings
BASE_Y_SPACING = 200    # base vertical spacing between levels
BASE_FONT_SIZE = 14
LABEL_WIDTH    = 30     # wrap width (chars) for non-metric nodes

# Your metric list (as provided). Note: FreeCashFlow is derived; excluded from taxonomy lookup.
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
    "FreeCashFlow",  # derived, not an XBRL element
]

# ----------------------------
# LOAD DTS + PRESENTATION
# ----------------------------
cntlr = Cntlr.Cntlr(logFileName=None)
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)
if model_xbrl is None:
    print(f"Failed to load entry point: {ENTRY_XSD}", file=sys.stderr); sys.exit(1)

pres = model_xbrl.relationshipSet(XbrlConst.parentChild)
if not pres or not getattr(pres, "modelRelationships", None):
    raise RuntimeError("No presentation relationships found in the loaded DTS.")

roles = getattr(pres, "linkRoleUris", None) or sorted({rel.linkrole for rel in pres.modelRelationships})
print("presentation networks:", len(roles))

# ----------------------------
# HELPERS
# ----------------------------
def role_label(model_xbrl, role_uri: str, lang: str = "en") -> str:
    try:
        lbl = model_xbrl.roleTypeDefinition(role_uri, lang=lang)
        if lbl: return lbl
    except Exception:
        pass
    return role_uri.rsplit("/", 1)[-1]

def roots_for_role(pres, role_uri: str):
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri:
            parents.add(rel.fromModelObject); children.add(rel.toModelObject)
    return list(parents - children)

def build_forest_for_role(pres, role_uri: str, roots):
    nodes = {c: {"id": str(c.qname),
                 "label": c.label(lang="en") or str(c.qname),
                 "children": []} for c in roots}
    q = deque(roots)
    while q:
        parent = q.popleft()
        for rel in pres.fromModelObject(parent):
            if rel.linkrole != role_uri: continue
            child = rel.toModelObject
            if child not in nodes:
                nodes[child] = {"id": str(child.qname),
                                "label": child.label(lang="en") or str(child.qname),
                                "children": []}
            nodes[parent]["children"].append(nodes[child]); q.append(child)
    return [nodes[r] for r in roots]

def collect_ids_from_nodes(nodes):
    ids, stack = set(), list(nodes)
    while stack:
        n = stack.pop()
        ids.add(n["id"]); stack.extend(n.get("children", []))
    return ids

def wrap_label(s: str, width: int = 28) -> str:
    parts, line, lines = s.split(), "", []
    for w in parts:
        if len(line) + len(w) + (1 if line else 0) <= width:
            line = (line + " " + w).strip()
        else:
            lines.append(line); line = w
    if line: lines.append(line)
    return "\n".join(lines)

def safe_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:limit] or "role"

def build_adjacency(nodes_list):
    children, parents = defaultdict(list), defaultdict(list)
    stack = list(nodes_list)
    seen = set()
    while stack:
        node = stack.pop()
        nid = node["id"]
        if nid not in seen: seen.add(nid)
        for ch in node.get("children", []):
            cid = ch["id"]
            children[nid].append(cid); parents[cid].append(nid); stack.append(ch)
    all_ids = set(children.keys()) | set(parents.keys())
    roots_ids = sorted(all_ids - set(parents.keys()))
    return children, parents, roots_ids

def find_path_from_any_root_to_target(children, parents, roots_ids, target_id):
    from collections import deque as _dq
    q = _dq(); prev = {}; visited = set()
    for r in roots_ids: q.append(r); visited.add(r); prev[r] = None
    while q:
        u = q.popleft()
        if u == target_id:
            path = []; cur = u
            while prev[cur] is not None:
                path.append((prev[cur], cur)); cur = prev[cur]
            path.reverse(); return path
        for v in children.get(u, []):
            if v not in visited: visited.add(v); prev[v] = u; q.append(v)
    return []

# ----------------------------
# Build role forests + maps
# ----------------------------
role_to_nodes, role_to_ids, role_to_graph = {}, {}, {}
for uri in roles:
    r_roots  = roots_for_role(pres, uri)
    r_forest = build_forest_for_role(pres, uri, r_roots)
    role_to_nodes[uri] = r_forest
    role_to_ids[uri]   = collect_ids_from_nodes(r_forest)
    role_to_graph[uri] = build_adjacency(r_forest)

# Which roles contain your metrics? (exclude derived 'FreeCashFlow' from taxonomy lookup)
lookup_metrics = [m for m in METRICS if m != "FreeCashFlow"]
metric_qnames  = {f"us-gaap:{m}" for m in lookup_metrics}
roles_of_interest, role_metrics_map = [], defaultdict(list)
for uri in roles:
    hits = sorted([m for m in metric_qnames if m in role_to_ids[uri]])
    if hits:
        roles_of_interest.append(uri)
        role_metrics_map[uri] = [h.split(":", 1)[-1] for h in hits]

print(f"roles containing your metrics: {len(roles_of_interest)}")

# ----------------------------
# Export per-role graphs (metric nodes 6× larger)
# ----------------------------
out = Path(OUT_DIR); out.mkdir(parents=True, exist_ok=True)

def export_role_graph(role_uri: str):
    role_name = role_label(model_xbrl, role_uri)
    nodes_list = role_to_nodes[role_uri]
    children_map, parents_map, roots_ids = role_to_graph[role_uri]

    metric_set = {f"us-gaap:{m}" for m in role_metrics_map.get(role_uri, [])}

    # Paths to metrics
    edges_on_path, nodes_on_path = set(), set()
    for target_id in metric_set:
        for e in find_path_from_any_root_to_target(children_map, parents_map, roots_ids, target_id):
            edges_on_path.add(e); nodes_on_path.update(e)

    # Level rows + labels + all edges
    order_by_level, labels, edges_all = defaultdict(list), {}, set()
    dq = deque((node, 0) for node in nodes_list)
    seen_pair = set()
    while dq:
        node, d = dq.popleft()
        nid = node["id"]; labels.setdefault(nid, node["label"])
        if nid not in order_by_level[d]: order_by_level[d].append(nid)
        for ch in node.get("children", []):
            cid = ch["id"]; labels.setdefault(cid, ch["label"])
            edges_all.add((nid, cid))
            pair = (cid, d + 1)
            if pair not in seen_pair: seen_pair.add(pair); dq.append((ch, d + 1))

    # Rows with metrics get scaled spacing
    depths = sorted(order_by_level.keys())
    row_has_metric = {d: any(n in metric_set for n in order_by_level[d]) for d in depths}
    row_y_spacing  = {d: int(BASE_Y_SPACING * (METRIC_SCALE if row_has_metric[d] else 1.0)) for d in depths}
    depth_y, y_pos = {}, 0
    for d in depths: depth_y[d] = y_pos; y_pos += row_y_spacing[d]

    # Network (physics off)
    net = Network(height="900px", width="100%", directed=True, bgcolor="#ffffff")
    net.set_options(json.dumps({
        "physics": {"enabled": False},
        "interaction": {"hover": True, "dragNodes": False, "zoomView": True},
        "nodes": {"shape": "box", "font": {"size": BASE_FONT_SIZE, "multi": True}, "margin": 10, "widthConstraint": {"maximum": 280}},
        "edges": {"arrows": {"to": {"enabled": True}}}
    }))

    # Colors
    METRIC_BG, METRIC_BG_HI, RED = "#DDF7E3", "#C9F4D7", "#d32f2f"

    # Size & font for metric nodes (~6×)
    metric_size = int(20 * METRIC_SCALE)               # 20→120 when scale=6
    metric_font = max(int(BASE_FONT_SIZE * 1.8), 20)   # readable boost

    # Place nodes with fixed positions (centered per row)
    added = set()
    for d in depths:
        row = order_by_level[d]
        if not row: continue
        xs = int(BASE_X_SPACING * (METRIC_SCALE if row_has_metric[d] else 1.0))  # widen rows with metrics
        start_x = -((len(row) - 1) * xs) / 2
        for i, nid in enumerate(row):
            if nid in added: continue
            x = start_x + i * xs
            y = depth_y[d]
            is_metric = nid in metric_set
            label_wrapped = wrap_label(labels.get(nid, nid), 22 if is_metric else LABEL_WIDTH)

            if is_metric:
                # Metric node: ellipse with explicit size → visually ~6× bigger
                net.add_node(
                    nid, label=label_wrapped,
                    title=f"{html.escape(nid)}<br><b>METRIC</b>",
                    shape="ellipse", size=metric_size,
                    color={"border": RED, "background": METRIC_BG,
                           "highlight": {"border": RED, "background": METRIC_BG_HI},
                           "hover": {"border": RED, "background": METRIC_BG_HI}},
                    font={"size": metric_font, "multi": True, "bold": True},
                    x=x, y=y, physics=False, fixed=True
                )
            elif nid in nodes_on_path:
                net.add_node(
                    nid, label=label_wrapped, title=html.escape(nid),
                    borderWidth=3, color={"border": RED},
                    x=x, y=y, physics=False, fixed=True
                )
            else:
                net.add_node(
                    nid, label=label_wrapped, title=html.escape(nid),
                    x=x, y=y, physics=False, fixed=True
                )
            added.add(nid)

    # Edges (highlight path edges)
    for u, v in edges_all:
        if (u, v) in edges_on_path:
            net.add_edge(u, v, color=RED, width=3)
        else:
            net.add_edge(u, v)

    fname = f"{safe_filename(role_name)}.html"
    target = out / fname
    net.write_html(str(target))
    return fname, role_name

# Generate graphs + index
index_rows = []
for uri in sorted(roles_of_interest, key=lambda u: role_label(model_xbrl, u).lower()):
    fname, role_name = export_role_graph(uri)
    metrics_str = ", ".join(role_metrics_map[uri])
    index_rows.append((role_name, uri, metrics_str, fname))

index_html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>US-GAAP roles containing metrics ({len(index_rows)} roles)</title>
  <style>
    body {{ font: 14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial; margin: 28px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e5e5e5; padding: 8px 10px; vertical-align: top; }}
    th {{ background: #f7f7f7; position: sticky; top: 0; }}
    code {{ background: #f3f3f3; padding: 2px 4px; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>US-GAAP presentation roles containing your metrics</h1>
  <p>Entry point: <code>{html.escape(ENTRY_XSD)}</code></p>
  <p>Metrics searched (derived <b>FreeCashFlow</b> excluded from lookups): <code>{", ".join(html.escape(m) for m in METRICS)}</code></p>
  <table>
    <thead>
      <tr><th>Role label</th><th>Role URI</th><th>Metrics in role</th><th>Graph</th></tr>
    </thead>
    <tbody>
"""
for role_name, uri, metrics_str, fname in index_rows:
    index_html += (
        f"<tr><td>{html.escape(role_name)}</td>"
        f"<td><code>{html.escape(uri)}</code></td>"
        f"<td>{html.escape(metrics_str) if metrics_str else '(none)'}</td>"
        f"<td><a href='{html.escape(fname)}'>open</a></td></tr>\n"
    )

index_html += """    </tbody>
  </table>
  <p><small>Legend: metric nodes are ellipses (~6× size) with light-green fill and red border. All nodes/edges on root→metric paths use red borders/edges.</small></p>
</body>
</html>
"""

index_path = (Path(OUT_DIR) / "index.html")
index_path.write_text(index_html, encoding="utf-8")
print("Per-role graphs exported to:", OUT_DIR)
print("Index:", index_path)
