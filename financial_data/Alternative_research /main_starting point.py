
from cosine_similarity_selection import choose_revenue_substitute
from proximity_similarity import choose_revenue_substitute_proximity,proximity_score
from hybrid_sim import choose_revenue_substitute_hybrid
from structural_similarity import choose_revenue_substitute_by_descendants

# ───────── SCRIPT ENTRYPOINT ————————————————————————————————————
if __name__ == "__main__":
    CIK = "0000320193"  # Apple Inc.
    #target_label = "NetIncomeLoss"
    target_label = "EarningsPerShareDiluted"
    # Example 1: cosine only
    x=choose_revenue_substitute(CIK,target_label,top_n=5)
    print('test',x)

    # Example 2: proximity only
    #choose_revenue_substitute_proximity(CIK,top_n=5)

    # Example 3: hybrid
    #choose_revenue_substitute_hybrid(top_n=1, alpha=0.6)
    choose_revenue_substitute_by_descendants(CIK,target_label,top_n=5)