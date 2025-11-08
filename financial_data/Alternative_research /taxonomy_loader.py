from pathlib import Path
import requests
import lxml.etree as ET
from helper import _dl

HEADERS      = {"User-Agent": "eng.sultan.fadi@gmail.com (semantic-revenue-finder)"}
YEAR_CUTOFF  = 2014
TRY_YEARS    = ("2024", "2023")      # first one found will be used
CACHE_DIR    = Path("../.cache"); CACHE_DIR.mkdir(exist_ok=True)

# ───────── LOAD TAXONOMY LABEL+DEFINITION TEXTS ——————————————

def taxo_texts() -> dict:
    """
    Return {tag: "<label + definition>"} for a usable taxonomy year in TRY_YEARS.
    """
    for yr in TRY_YEARS:
        base   = f"https://xbrl.fasb.org/us-gaap/{yr}/elts"
        lab_fp = CACHE_DIR / f"lab_{yr}.xml"
        doc_fp = CACHE_DIR / f"doc_{yr}.xml"
        try:
            _dl(f"{base}/us-gaap-lab-{yr}.xml", lab_fp)
            _dl(f"{base}/us-gaap-doc-{yr}.xml", doc_fp)

            ns = {"link": "http://www.xbrl.org/2003/linkbase"}
            texts = {}

            # Standard labels
            for lb in ET.parse(lab_fp).iterfind(".//link:label", ns):
                role = lb.get("{http://www.w3.org/1999/xlink}role", "")
                if role.endswith("/label"):
                    tag = lb.get("{http://www.w3.org/1999/xlink}label", "").split("_", 1)[-1]
                    if tag:
                        texts.setdefault(tag, []).append(lb.text or "")

            # Documentation labels (definitions)
            for lb in ET.parse(doc_fp).iterfind(".//link:label", ns):
                role = lb.get("{http://www.w3.org/1999/xlink}role", "")
                if role.endswith("/documentation"):
                    tag = lb.get("{http://www.w3.org/1999/xlink}label", "").split("_", 1)[-1]
                    if tag:
                        texts.setdefault(tag, []).append(lb.text or "")

            return {k: " ".join(v) for k, v in texts.items()}

        except requests.HTTPError:
            continue
    raise RuntimeError("Couldn’t download any of the requested taxonomy years.")
