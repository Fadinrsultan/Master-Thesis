from collections import defaultdict, deque
from taxonomy_loader import taxo_texts
from tags_list import tags_list
from typing import Optional
from helper import _normalize
from arelle import Cntlr, XbrlConst

# ── UNIVERSAL GAAP‑2024 PRESENTATION FOREST ─────────────────────────────────────────────────
ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"

cntlr = Cntlr.Cntlr()
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)
pres = model_xbrl.relationshipSet(XbrlConst.parentChild)

# all link‑roles present
roles = {rel.linkrole for rel in pres.modelRelationships}
print("presentation networks:", len(roles))  # Check number of roles


# helper: roots = parents that are never children in that role
def roots_for_role(role_uri):
    parents, children = set(), set()
    for rel in pres.modelRelationships:
        if rel.linkrole == role_uri:
            parents.add(rel.fromModelObject)
            children.add(rel.toModelObject)
    return list(parents - children)  # Parents that are not children of any other concept


# Build the forest
forest = defaultdict(list)

for role in roles:
    roots = roots_for_role(role)
    nodes = {c: {"id": str(c.qname),
                 "label": c.label(lang="en") or str(c.qname),
                 "children": []}
             for c in roots}

    q = deque(roots)
    while q:
        parent = q.popleft()  # get the parent
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

print("forest built with",
      sum(len(v) for v in forest.values()), "top‑level nodes across",
      len(forest), "networks")


# ── TREE TRAVERSAL FUNCTIONS ─────────────────────────────────────────────────
def get_ancestors(tag, tree):
    """Get all ancestors of a tag in the tree."""
    ancestors = []
    current = tag
    while current in tree:
        ancestors.append(current)
        current = tree.get(current, [None])[0]  # Get the parent (assuming the first parent)
    return ancestors


def find_lca(tag1, tag2, tree):
    """Find the Lowest Common Ancestor (LCA) between two tags."""
    ancestors1 = get_ancestors(tag1, tree)
    ancestors2 = get_ancestors(tag2, tree)

    # Find the common ancestors
    common_ancestors = set(ancestors1).intersection(ancestors2)

    # The LCA is the deepest common ancestor
    for ancestor in ancestors1:
        if ancestor in common_ancestors:
            return ancestor
    return None  # No common ancestor found


def calculate_distance(tag1, tag2, tree):
    """Calculate the distance between two tags based on LCA."""
    lca = find_lca(tag1, tag2, tree)
    if not lca:
        return float('inf')  # No common ancestor, infinite distance

    # Calculate the distance from tag1 and tag2 to the LCA
    def distance_from_lca(tag, lca, tree):
        distance = 0
        current = tag
        while current != lca:
            current = tree.get(current, [None])[0]
            distance += 1
        return distance

    distance_tag1 = distance_from_lca(tag1, lca, tree)
    distance_tag2 = distance_from_lca(tag2, lca, tree)

    return distance_tag1 + distance_tag2  # Total distance


def get_descendants(tag, tree):
    """Get all descendants (subtree) of a given tag."""
    descendants = []

    def recursive_traversal(current_tag):
        children = tree.get(current_tag, [])
        for child in children:
            descendants.append(child)
            recursive_traversal(child)  # Recursively get descendants

    recursive_traversal(tag)
    return descendants


# ── MAIN FUNCTION TO GET THE NETWORK THAT CONTAINS THE TARGET LABEL ─────────────
def get_network_for_target_label(target_label, forest):
    """Get the network that contains the target label."""
    for role, networks in forest.items():
        for network in networks:
            if isinstance(network, dict):
                # Check if any node in the network contains the target label
                for node in network["children"]:
                    if node["label"].strip().lower() == target_label.strip().lower():
                        print(f"Found '{target_label}' in the network for role {role}.")
                        return network  # Return the network containing the target label
    return None  # Return None if the target label is not found in any network


# ── MAIN FUNCTION TO FIND TOP N SIMILAR TAGS BASED ON DESCENDANTS ─────────────
def choose_revenue_substitute_by_descendants(CIK, target_label, top_n=5) -> Optional[str]:
    """Choose structurally similar tags based on descendants in the taxonomy."""
    texts = taxo_texts()
    reported = tags_list(CIK)

    # Check if the target label exists in the taxonomy texts
    if target_label not in texts:
        print(f"Error: '{target_label}' not found in taxonomy texts.")
        return None

    # Get the network that contains the target label
    network_for_target = get_network_for_target_label(target_label, forest)
    if network_for_target is None:
        print(f"Error: Network containing '{target_label}' not found.")
        return None

    # Get descendants of the target tag (all tags in the subtree of 'Revenue')
    descendants = get_descendants(target_label, forest)  # 'forest' is your pre-built taxonomy tree

    # Create a list to store tags and their structural distances from the target
    distances = []

    # Calculate the LCA-based distance for each descendant tag
    for tag in descendants:
        if tag in texts:  # Check if the tag exists in the taxonomy
            distance = calculate_distance(target_label, tag, forest)
            distances.append((tag, distance))

    # Sort by distance (closer tags have smaller distance)
    sorted_tags = sorted(distances, key=lambda x: x[1])

    # Output top N structurally similar tags based on LCA distance
    print("\nTop structurally similar tags (based on descendants) — LCA distance")
    print("──────────────────────────────────────────────────────────────────")
    for i, (tag, dist) in enumerate(sorted_tags[:top_n], 1):
        print(f"{i:>2}. {tag:<60}  distance = {dist}")
    print("──────────────────────────────────────────────────────────────────")

    return sorted_tags[0][0] if sorted_tags else None


# ── EXAMPLE USAGE ───────────────────────────────────────────────────────
result = choose_revenue_substitute_by_descendants(CIK="0000320193", target_label="Revenues", top_n=5)
print(f"Chosen substitute → {result}")
