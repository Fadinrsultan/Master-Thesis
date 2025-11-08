# ── US-GAAP 2025: Plot ALL top-level roots (≈119) on one canvas (grid layout, labels visible)
from pathlib import Path
from collections import defaultdict, deque
from arelle import Cntlr, XbrlConst
from pyvis.network import Network
import html, json, math, sys, webbrowser

# ----------------------------
# 1) CONFIG
# ----------------------------
ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"
OUT_HTML  = "/Users/fadisultan/Downloads/usgaap_roots_119_grid.html"  # output HTML

# ----------------------------
# 2) LOAD DTS + PRESENTATION RELS
# ----------------------------
cntlr = Cntlr.Cntlr(logFileName=None)
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)
if model_xbrl is None:
    print("Failed to load entry point:", ENTRY_XSD, file=sys.stderr)
    sys.exit(1)

pres = model_xbrl.relationshipSet(XbrlConst.parentChild)
if not pres or not getattr(pres, "modelRelationships", None):
    raise RuntimeError("No presentation relationships found in the loaded DTS.")

# all link-roles present
roles = {rel.linkrole for rel in pres.modelRelationships}
print("presentation networks:", len(roles))

# ----------------------------
# 3) HELPERS
# ----------------------------
def roots_for_role(role_uri):
    """Parents that are never children in that role → top-level roots for that network."""
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri:
            parents.add(rel.fromModelObject)
            children.add(rel.toModelObject)
    return list(parents - children)

def role_label(model_xbrl, role_uri, lang="en"):
    """Human-friendly role label if available; otherwise tail of URI."""
    try:
        lbl = model_xbrl.roleTypeDefinition(role_uri, lang=lang)
        if lbl:
            return lbl
    except Exception:
        pass
    return role_uri.rsplit("/", 1)[-1]

def wrap_label(s, width=28):
    """Optional: wrap long labels to multiple lines for nicer boxes."""
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\n".join(lines)

# ----------------------------
# 4) BUILD THE FOREST  { role_uri: [ {id,label,children:[...]}, ... ] }
# ----------------------------
forest = defaultdict(list)

for role in roles:
    roots = roots_for_role(role)
    nodes = {c: {"id": str(c.qname),
                 "label": c.label(lang="en") or str(c.qname),
                 "children": []}
             for c in roots}

    q = deque(roots)
    while q:
        parent = q.popleft()
        for rel in pres.fromModelObject(parent):
            if rel.linkrole != role:
                continue
            child = rel.toModelObject
            if child not in nodes:
                nodes[child] = {"id": str(child.qname),
                                "label": child.label(lang="en") or str(child.qname),
                                "children": []}
            nodes[parent]["children"].append(nodes[child])
            q.append(child)

    forest[role] = [nodes[r] for r in roots]

total_roots = sum(len(v) for v in forest.values())
print("forest built with", total_roots, "top-level nodes across", len(forest), "networks")

# ----------------------------
# 5) PLOT: ALL TOP-LEVEL ROOTS ON ONE CANVAS (GRID, NO EDGES)
# ----------------------------
def plot_all_roots_one_graph_grid(
    forest,
    model_xbrl,
    out_file=OUT_HTML,
    font_size=16,
    spacing=260,      # pixels between nodes
    max_label_width=28
):
    """
    Single interactive graph of all top-level roots (≈119),
    arranged on a fixed grid with labels forced visible.
    """
    net = Network(height="1000px", width="100%", directed=False, bgcolor="#ffffff")
    net.set_options(json.dumps({
        "physics": {"enabled": False},
        "layout": {"improvedLayout": True},
        "interaction": {"hover": True, "dragNodes": False, "zoomView": True},
        "nodes": {"shape": "box", "font": {"size": font_size}}
    }))

    # Flatten roots with their role labels
    roots_flat = []
    for role_uri, roots in sorted(forest.items(), key=lambda kv: role_label(model_xbrl, kv[0]).lower()):
        group_name = role_label(model_xbrl, role_uri)
        for r in roots:
            roots_flat.append((role_uri, group_name, r))

    n = len(roots_flat)
    if n == 0:
        raise RuntimeError("No top-level roots to plot.")
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)

    # Center the grid around (0,0)
    x0 = -((cols - 1) * spacing) / 2
    y0 = -((rows - 1) * spacing) / 2

    added = set()
    for i, (role_uri, group_name, r) in enumerate(roots_flat):
        row, col = divmod(i, cols)
        x = x0 + col * spacing
        y = y0 + row * spacing
        nid = f"{role_uri}|{r['id']}"
        if nid in added:
            continue
        label_wrapped = wrap_label(r["label"], width=max_label_width)
        net.add_node(
            nid,
            label=label_wrapped,
            title=f"{html.escape(r['id'])}<br>Role: {html.escape(group_name)}",
            group=group_name,
            x=x, y=y, physics=False, fixed=True
        )
        added.add(nid)

    out = Path(out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out))  # pyvis needs a string path
    try:
        webbrowser.open_new_tab(out.as_uri())
    except Exception:
        pass
    print(f"[OK] Grid view written → {out} | nodes={len(added)} | grid={rows}x{cols}")

# ----------------------------
# 6) RUN
# ----------------------------
plot_all_roots_one_graph_grid(forest, model_xbrl, OUT_HTML)
