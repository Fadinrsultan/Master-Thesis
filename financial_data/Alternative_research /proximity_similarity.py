from helper import _tokenize_positions
from typing import Optional
from taxonomy_loader import taxo_texts
from tags_list import tags_list

def proximity_score(text: str) -> float:
    """
    Proximity similarity in [0,1].
    Backed off to a frequency score: count / (count + 5).
    """
    tokens = _tokenize_positions(text)
    count = sum(1 for t in tokens)
    return count / (count + 5.0)

def choose_revenue_substitute_proximity(CIK,top_n: int = 5) -> Optional[str]:
    texts = taxo_texts()
    reported = tags_list(CIK)

    # Build candidate set
    cand = []
    for t in reported:
        if t in texts:
            cand.append((t, texts[t]))

    if not cand:
        print("No candidate tags found with available taxonomy texts.")
        return None

    # Score by proximity against each tag's label+definition
    scored = []
    for tag, txt in cand:
        s = proximity_score(txt)
        scored.append((tag, s))

    ranked = sorted(scored, key=lambda x: x[1], reverse=True)[:top_n]

    print("\nTop proximity matches to revenue cues (Apple) — PROXIMITY")
    print("───────────────────────────────────────────────────────────")
    for i, (tag, sc) in enumerate(ranked, 1):
        print(f"{i:>2}. {tag:<60}  proximity = {sc:.3f}")
    print("───────────────────────────────────────────────────────────")
    print(f"Chosen substitute → {ranked[0][0]}" if ranked else "No candidate found.")
    return ranked[0][0] if ranked else None

