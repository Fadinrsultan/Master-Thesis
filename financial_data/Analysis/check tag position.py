"""
US-GAAP 2025 — Find which PRESENTATION role(s) contain specific us-gaap tags.

Requirements (install once in your venv):
    pip install arelle-release

Usage:
    - Set ENTRY_XSD to your local US-GAAP 2025 entry point.
    - Run the script. It prints roles per metric and writes a CSV.

Notes:
    - We search the Presentation linkbase (arcrole: parent-child).
    - 'FreeCashFlow' is a derived metric, not an XBRL concept, so it won't be found.
"""

from collections import defaultdict, deque
from pathlib import Path
import csv, sys

from arelle import Cntlr, XbrlConst   # Arelle API


# ----------------------------
# 0) CONFIG
# ----------------------------
ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"
OUT_CSV   = "/Users/fadisultan/Downloads/usgaap_metric_roles.csv"

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
    "FreeCashFlow",  # derived (not an XBRL element)
]


# ----------------------------
# 1) LOAD DTS + PRESENTATION RELATIONSHIPS
# ----------------------------
def load_presentation(entry_xsd: str):
    cntlr = Cntlr.Cntlr(logFileName=None)
    model_xbrl = cntlr.modelManager.load(entry_xsd)
    if model_xbrl is None:
        print(f"Failed to load entry point: {entry_xsd}", file=sys.stderr)
        sys.exit(1)

    pres = model_xbrl.relationshipSet(XbrlConst.parentChild)
    if not pres or not getattr(pres, "modelRelationships", None):
        raise RuntimeError("No presentation relationships found in the loaded DTS.")

    # Role URIs present in the presentation network
    roles = getattr(pres, "linkRoleUris", None)
    if not roles:
        roles = sorted({rel.linkrole for rel in pres.modelRelationships})

    return model_xbrl, pres, list(roles)


# ----------------------------
# 2) HELPERS
# ----------------------------
def role_label(model_xbrl, role_uri: str, lang: str = "en") -> str:
    """Human-friendly role name, falling back to the last path segment."""
    try:
        lbl = model_xbrl.roleTypeDefinition(role_uri, lang=lang)
        if lbl:
            return lbl
    except Exception:
        pass
    return role_uri.rsplit("/", 1)[-1]


def roots_for_role(pres, role_uri: str):
    """Top-level roots per role: parents that are not children in the SAME role."""
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri:
            parents.add(rel.fromModelObject)
            children.add(rel.toModelObject)
    return list(parents - children)


def collect_concept_ids_for_role(pres, role_uri: str, roots) -> set:
    """Traverse the presentation tree for a role and return a set of concept QNames as strings (e.g., 'us-gaap:Revenues')."""
    ids = set()
    q = deque(roots)
    while q:
        parent = q.popleft()
        ids.add(str(parent.qname))
        for rel in pres.fromModelObject(parent):
            if rel.linkrole != role_uri:
                continue
            child = rel.toModelObject
            ids.add(str(child.qname))
            q.append(child)
    return ids


# ----------------------------
# 3) MAIN LOGIC — BUILD role → {concept ids}, THEN MAP METRICS → roles
# ----------------------------
def find_metrics_in_presentation(entry_xsd: str, metrics: list, out_csv: str):
    model_xbrl, pres, roles = load_presentation(entry_xsd)
    print(f"presentation networks: {len(roles)}")

    # Build role → set(concept IDs present in that role's presentation tree)
    role_to_ids = {}
    for role_uri in roles:
        roots = roots_for_role(pres, role_uri)
        ids = collect_concept_ids_for_role(pres, role_uri, roots)
        role_to_ids[role_uri] = ids

    # Query for each metric
    results_rows = []  # for CSV
    for m in metrics:
        print(f"\n▸ {m}:")
        if m == "FreeCashFlow":
            print("   • Derived metric (Operating CF − CapEx). Not an XBRL concept.")
            results_rows.append([m, "Derived (not in taxonomy)", ""])
            continue

        qid = f"us-gaap:{m}"
        hits = []
        for role_uri, ids in role_to_ids.items():
            if qid in ids:
                hits.append((role_uri, role_label(model_xbrl, role_uri)))

        if hits:
            # Sort by human label for readability
            hits.sort(key=lambda x: x[1].lower())
            for uri, lbl in hits:
                kind = "statement" if "/statement/" in uri else ("disclosure" if "/disclosure/" in uri else "other")
                print(f"   • [{kind}] {lbl}  →  {uri}")
                results_rows.append([m, lbl, uri])
        else:
            print("   • Not found in presentation networks loaded.")
            results_rows.append([m, "(none)", ""])

    # Write CSV
    p = Path(out_csv)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "role_label", "role_uri"])
        w.writerows(results_rows)
    print(f"\nCSV written → {p}")


# ----------------------------
# 4) RUN
# ----------------------------
if __name__ == "__main__":
    find_metrics_in_presentation(ENTRY_XSD, METRICS, OUT_CSV)
