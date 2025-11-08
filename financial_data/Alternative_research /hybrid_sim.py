from helper import _tokenize_positions,_normalize
from typing import Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from taxonomy_loader import taxo_texts
from tags_list import tags_list
from sklearn.metrics.pairwise import cosine_similarity
from proximity_similarity import proximity_score

def choose_revenue_substitute_hybrid(top_n: int = 5, alpha: float = 0.6) -> Optional[str]:
    texts = taxo_texts()
    reported = tags_list(CIK)

    if "Revenues" in texts:
        target_label = texts["Revenues"]
    elif "RevenueFromContractWithCustomerExcludingAssessedTax" in texts:
        target_label = texts["RevenueFromContractWithCustomerExcludingAssessedTax"]
    else:
        raise RuntimeError("No target revenue concept found in taxonomy texts.")

    corpus   = [_normalize(target_label)]
    tag_list = []
    for t in reported:
        if t in texts:
            corpus.append(_normalize(texts[t]))
            tag_list.append(t)

    if len(tag_list) == 0:
        print("No overlapping tags between Apple-reported set and taxonomy texts.")
        return None

    vec  = TfidfVectorizer().fit_transform(corpus)
    sims = cosine_similarity(vec[0:1], vec[1:]).ravel()

    prox_scores = [proximity_score(texts[tag]) for tag in tag_list]

    blended = []
    for tag, csc, psc in zip(tag_list, sims, prox_scores):
        score = alpha * float(csc) + (1.0 - alpha) * float(psc)
        blended.append((tag, score, csc, psc))

    ranked = sorted(blended, key=lambda x: x[1], reverse=True)[:top_n]

    print("\nTop HYBRID matches to revenue cues (Apple) — HYBRID")
    print("────────────────────────────────────────────────────")
    for i, (tag, score, csc, psc) in enumerate(ranked, 1):
        print(f"{i:>2}. {tag:<60}  blended={score:.3f}  cos={csc:.3f}  prox={psc:.3f}")
    print("────────────────────────────────────────────────────")
    print(f"Chosen substitute → {ranked[0][0]}" if ranked else "No candidate found.")
    return ranked[0][0] if ranked else None