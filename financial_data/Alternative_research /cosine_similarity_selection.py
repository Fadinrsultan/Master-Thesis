from taxonomy_loader import taxo_texts
from tags_list import tags_list
from sklearn.feature_extraction.text import  TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import Optional
from helper import _normalize


# ───────── COSINE SIMILARITY SELECTION ——————————————————————————

def choose_revenue_substitute(CIK,target_label,top_n: int = 5) -> Optional[str]:
    texts = taxo_texts()
    reported = tags_list(CIK)
    #target_label = target_label
    target_label = texts[target_label]
     #1) What string will stand in for the *missing* target?
    #if "Revenues" in texts:
        #target_label = texts["Revenues"]
    #elif "RevenueFromContractWithCustomerExcludingAssessedTax" in texts:
        #target_label = texts["RevenueFromContractWithCustomerExcludingAssessedTax"]
    #else:
        #raise RuntimeError("No target revenue concept found in taxonomy texts.")

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

    ranking = sorted(zip(tag_list, sims), key=lambda x: x[1], reverse=True)[:top_n+1]

    print(f"\nTop semantic matches to missing tag concept ({CIK}) — COSINE")
    print("──────────────────────────────────────────────────────────────────")
    #print(f"{ranking[0][0]}, similarity = {ranking[0][1]:.3f}")

    for i, (tag, sc) in enumerate(ranking, 1):
        if i<6:
              print(f"{i}. {tag:<60}  similarity = {sc:.3f}")
    print("──────────────────────────────────────────────────────────────────")
    print(f"Chosen substitute → {(ranking[0][0] if ranking[0][1] < 1.0 else ranking[1][0])}" if ranking else "No candidate found.")
    return ranking[0][0] if ranking[0][1] < 1.0 else ranking[1][0]
    #return ranking if ranking else None