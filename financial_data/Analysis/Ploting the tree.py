# ── UNIVERSAL GAAP‑2024 PRESENTATION FOREST
from pathlib import Path
'''convert the local file path (like /Users/fadisultan/Downloads/soi_network.html) into a URI (file:///...) 
so it can be safely opened in a browser tab'''
from collections import defaultdict, deque
#defaultdict:like a regular dict, but it automatically creates a default value if a key is missing—so you don’t get a KeyError
#A deque is a list-like container that allows fast appends and pops from both ends—ideal for queues or stacks.
from arelle import Cntlr, XbrlConst
'''Arelle framework — an open-source tool for working with XBRL (eXtensible Business Reporting Language) data.
#Cntlr: Initializes and manages XBRL models and file loading
#XbrlConst:
'''

ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"

cntlr      = Cntlr.Cntlr()
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)#load .xsd file
pres       = model_xbrl.relationshipSet(XbrlConst.parentChild)#gets all the presentation relationships in the XBRL model.

# all link‑roles present
roles = {rel.linkrole for rel in pres.modelRelationships}
'''A role tells you which part of a financial report a group of XBRL elements belongs to — for example:

Balance Sheet
Income Statement
Statement of Cash Flows
Statement of Shareholders’ Equity'''
print("presentation networks:", len(roles))                 # 116
# helper: roots = parents that are never children in that role
def roots_for_role(role_uri):
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri:#To only process relationships that belong to a specific role.
            parents.add(rel.fromModelObject)#adds every parent concept in that role
            children.add(rel.toModelObject)#adds every child concept in that role
    #print("parents_children:",list(parents - children))
    return list(parents - children)#parents that are not children of any other concept in the same role.
'''You need them because they are the starting points for building the presentation tree (or forest) for each role 
   (financial section) in the XBRL taxonomy.'''



# build the forest
forest = defaultdict(list)

for role in roles:
    roots = roots_for_role(role)
    nodes = {c: {"id": str(c.qname),
                 "label": c.label(lang="en") or str(c.qname),
                 "children": []}
             for c in roots}
    '''{
  <Concept us-gaap:IncomeStatementAbstract>: {
    "id": "us-gaap:IncomeStatementAbstract",
    "label": "Income Statement",
    "children": []# filled later
  }
}
'''

    q = deque(roots)
    while q:
        parent = q.popleft() # get the parent
        for rel in pres.fromModelObject(parent):           # ← no role arg
            if rel.linkrole != role:                       # manual filter
                continue
            child = rel.toModelObject
            if child not in nodes:
                nodes[child] = {"id": str(child.qname),
                                "label": child.label(lang="en") or str(child.qname),
                                "children": []}
            nodes[parent]["children"].append(nodes[child])
            q.append(child)

    forest[role] = [nodes[r] for r in roots]

'''forest["http://fasb.org/.../StatementOfIncome"] = [
  {
    "id": "us-gaap:IncomeStatementAbstract",
    "label": "Income Statement",
    "children": [
      {
        "id": "us-gaap:Revenues",
        "label": "Revenues",
        "children": [...]
      },
      ...
    ]
  }
]
'''
print("forest built with",
      sum(len(v) for v in forest.values()), "top‑level nodes across",
      len(forest), "networks")

print("Available roles:")
for r in forest.keys():
    print(" •", r)

from pyvis.network import Network
import networkx as nx, webbrowser, pathlib

def show_network(forest, role_uri, html_path):
    if role_uri not in forest:
        raise ValueError(f"role not found → {role_uri}")

    G, stack = nx.DiGraph(), list(forest[role_uri])
    while stack:
        node = stack.pop()
        for child in node["children"]:
            G.add_edge(node["label"], child["label"])
            stack.append(child)

    net = Network(height="900px", width="100%", directed=True, bgcolor="#ffffff")
    net.from_nx(G)
    net.write_html(html_path)          # safer than .show()
    webbrowser.open_new_tab(pathlib.Path(html_path).as_uri())
    print("HTML written and opened →", html_path)


#role_uri = "http://fasb.org/us-gaap/role/statement/StatementOfIncome"  #
#role_uri = "http://fasb.org/us-gaap/role/statement/StatementOfCashFlowsDirect"
#role_uri ="http://fasb.org/us-gaap/role/disclosure/InvestmentsEquityMethodAndJointVentures"
role_uri = "http://fasb.org/us-gaap/role/statement/StatementOfIncomeInterestBasedRevenue"
#role_uri ="http://fasb.org/us-gaap/role/deprecated/deprecated"
out_file = "/Users/fadisultan/Downloads/soi_network.html"

show_network(forest, role_uri, out_file)
