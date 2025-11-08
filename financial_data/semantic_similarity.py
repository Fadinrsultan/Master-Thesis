
import json, re, string, time, unicodedata
from pathlib import Path

import lxml.etree as ET
import requests
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ───────── CONFIG ————————————————————————————————————————————————
HEADERS      = {"User-Agent": "eng.sultan.fadi@gmail.com (semantic-revenue-finder)"}
CIK          = "0000320193"          # Apple Inc.
YEAR_CUTOFF  = 2014
TRY_YEARS    = ("2024", "2023")      # first one found will be used
CACHE_DIR    = Path("../.cache"); CACHE_DIR.mkdir(exist_ok=True)

FACTS_URL    = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"

# Maps common synonyms to the canonical token “revenue”?????
DOMAIN_SYNS  = {"sales": "revenue", "turnover": "revenue"}
'''Better statistics  cosine similarity, or language‑model counts
 are more reliable when every synonym contributes to the same feature.'''

# ───────── SMALL UTILITIES ————————————————————————————————————————
'''_dl() is a tiny, self‑contained download‑and‑cache utility: 
fetch a remote file only if you don’t already have it, save it atomically'''
def _dl(url: str, fp: Path):
    if fp.exists(): return #Checks whether the target file already lives on disk
    r = requests.get(url, headers=HEADERS, timeout=30); r.raise_for_status()
    #Sends an HTTP GET request for url
    #r.raise_for_status():Immediately raises an HTTPError if the response status code is 4xx or 5xx.
    fp.write_bytes(r.content); time.sleep(0.25)
'''use:
A.Holds every GAAP tag Apple has reported .
 APPLE FACTS:(…/api/xbrl/companyfacts/CIK0000320193.json)
B.Provides the human‑readable tag names ( “AdvertisingExpense,” etc.).
  (..us-gaap-lab-{yr}.xml", lab_fp)
C.Supplies the longer narrative descriptions used for the TF‑IDF similarity scoring.
   
'''

def _normalize(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt).lower()
    txt = re.sub(f"[{re.escape(string.punctuation)}]", " ", txt)
    return " ".join(DOMAIN_SYNS.get(w, w)
                    for w in txt.split() if w not in ENGLISH_STOP_WORDS)
'''"The company’s net sales—after returns—totaled €10 million."--->
company net revenue returns totaled 10 million
That tidy, synonym‑normalised string is what the TF‑IDF vectoriser sees—making
 “sales,” “turnover,” and “revenue” statistically identical, 
 and cutting noise from punctuation and stop‑words.
'''

# ───────── FETCH APPLE’s REPORTED TAGS —————————————————————————
def apple_tags() -> set[str]:
    fp = CACHE_DIR / "aapl_facts.json"; _dl(FACTS_URL, fp)
    facts = json.loads(fp.read_bytes()); tags = set()
    for tag, node in facts["facts"]["us-gaap"].items():
        if tag == "Revenues": continue                     # we know it’s absent
        for rows in node["units"].values():
            if any(int(r.get("fy", 0)) >= YEAR_CUTOFF for r in rows):
                tags.add(tag); break
    return tags
'''apple_tags() extracts every US‑GAAP tag Apple has used in 2014 present 
(except the unused generic Revenues tag) 
by scanning Apple’s company‑facts JSON. T
he resulting tag set becomes the candidate pool for finding the best
 “revenue” substitute later in the script.'''

# ───────── LOAD TAXONOMY LABEL+DEFINITION TEXTS ——————————————
def taxo_texts() -> dict[str, str]:
    for yr in TRY_YEARS:
        base = f"https://xbrl.fasb.org/us-gaap/{yr}/elts"#https://xbrl.fasb.org/us-gaap/2024/elts/
        lab_fp = CACHE_DIR / f"lab_{yr}.xml"#https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-lab-2024.xml
        doc_fp = CACHE_DIR / f"doc_{yr}.xml"#https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-doc-2024.xml
        try:
            _dl(f"{base}/us-gaap-lab-{yr}.xml", lab_fp)
            _dl(f"{base}/us-gaap-doc-{yr}.xml", doc_fp)
            '''_dl() fetches the file only if it is missing, then pauses 0.25s to stay polite to the FASB server.
               If either download returns an HTTP error (e.g., the taxonomy hasn’t been published for that year), 
               control jumps to the next year; only when all years fail does the function raise an exception.'''
            ns = {"link": "http://www.xbrl.org/2003/linkbase"}
            '''the US‑GAAP label linkbase stores the official human‑readable labels and narrative definitions 
            for every taxonomy concept. Those texts are transformed into TF‑IDF vectors so the algorithm can compare 
            Apple‑reported tags semantically and pick the closest substitute for the missing “Revenues” element, 
            used during similarity scoring.'''
            texts: dict[str, list[str]] = {}
            # Standard labels
            '''grabs every GAAP concept’s standard label: extracts the tag name from the xlink:label ID, 
            then saves its human‑readable English text in the texts dictionary for TF‑IDF scoring and comparisons.'''

            for lb in ET.parse(lab_fp).iterfind(".//link:label", ns):
                if lb.get("{http://www.w3.org/1999/xlink}role").endswith("/label"):
                    tag = lb.get("{http://www.w3.org/1999/xlink}label").split("_", 1)[-1]
                    texts.setdefault(tag, []).append(lb.text or "")
            #print("tags:",texts)
            # Documentation labels (definitions)
            for lb in ET.parse(doc_fp).iterfind(".//link:label", ns):
                if lb.get("{http://www.w3.org/1999/xlink}role").endswith("/documentation"):
                    tag = lb.get("{http://www.w3.org/1999/xlink}label").split("_", 1)[-1]
                    texts.setdefault(tag, []).append(lb.text or "")
            #print("docum", len(texts),texts)
            return {k: " ".join(v) for k, v in texts.items()}

        except requests.HTTPError:
            continue
    raise RuntimeError("Couldn’t download any of the requested taxonomy years.")
#print("test",taxo_texts())
# ───────── MAIN SELECTION LOGIC ————————————————————————————————
def choose_revenue_substitute(top_n: int = 5):
    texts = taxo_texts()
    reported = apple_tags()
    # 1) What string will stand in for the *missing* target?
    if "Revenues" in texts:
        print("Revenues tag applied.")
        target_label = texts["Revenues"]
        print(target_label)
    elif "RevenueFromContractWithCustomerExcludingAssessedTax" in texts:
        target_label = texts["RevenueFromContractWithCustomerExcludingAssessedTax"]


    corpus   = [_normalize(target_label)]
    print("normalized target",corpus)
    tag_list = []
    for t in sorted(reported):
        if t in texts:
            corpus.append(_normalize(texts[t])); tag_list.append(t)
    print("appended corpus",len(corpus),corpus)
    vec  = TfidfVectorizer().fit_transform(corpus)#??
    '''converts the list corpus—each item a string of label text—into a sparse numerical matrix where:

     1.fit builds a vocabulary of all unique terms across every document.
     2.transform computes each term’s TF‑IDF weight (term‑frequency scaled by inverse‑document‑frequency), 
     so common words get down‑weighted and distinctive words score higher.
     The resulting matrix vec has shape (documents×unique terms) and is ready for cosine‑similarity comparisons.'''

    print("vectorized corpus",vec.shape,vec)
    sims = cosine_similarity(vec[0:1], vec[1:]).ravel()
    '''`vec[0:1]` is the TF‑IDF vector for your **target revenue text**; `
        vec[1:]` is the matrix of vectors for every Apple tag.
`       cosine_similarity` computes the cosine of the angle between the target vector and each other vector, giving a similarity score\[0,1].
        .ravel()` flattens the 1×*n* result into a 1‑D array `sims`, where each element is “how revenue‑like this Apple tag is.
        '''

    ranking = sorted(zip(tag_list, sims), key=lambda x: x[1], reverse=True)[:top_n]

    print("\nTop semantic matches to missing revenue concept (Apple)")
    print("────────────────────────────────────────────────────────────")
    for i, (tag, sc) in enumerate(ranking, 1):
        print(f"{i:>2}. {tag:<60}  similarity = {sc:.3f}")
    print("────────────────────────────────────────────────────────────")
    print(f"Chosen substitute → {ranking[0][0]}" if ranking else "No candidate found.")
    return ranking[0][0]


choose_revenue_substitute()
