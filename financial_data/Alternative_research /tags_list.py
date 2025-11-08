from pathlib import Path
from typing import  List
import json
from helper import _dl
#CIK          = "0000320193"          # Apple Inc.
YEAR_CUTOFF  = 2014
TRY_YEARS    = ("2024", "2023")      # first one found will be used

CACHE_DIR    = Path("../.cache"); CACHE_DIR.mkdir(exist_ok=True)
# ───────── FETCH APPLE’S REPORTED TAGS —————————————————————————
def tags_list(CIK) -> List[str]:
    """Return GAAP tags Apple reported in YEAR_CUTOFF..present (excluding 'Revenues')."""
    FACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
    fp = CACHE_DIR / "aapl_facts.json"; _dl(FACTS_URL, fp)
    facts = json.loads(fp.read_bytes())
    tags = set()
    for tag, node in facts["facts"]["us-gaap"].items():
        if tag == "Revenues":
            continue  # we know it’s absent
        # Keep tag if any unit has an FY >= cutoff
        for rows in node.get("units", {}).values():
            if any(int(r.get("fy", 0)) >= YEAR_CUTOFF for r in rows):
                tags.add(tag); break
    return sorted(tags)