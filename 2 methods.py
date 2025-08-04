"""
Apple Inc. – rank candidate revenue tags two ways *with scores*
────────────────────────────────────────────────────────────────────────────
METHOD A  semantic_similarity()     → cosine TF-IDF score (higher = closer)
METHOD B  granularity_difference()  → depth difference (lower = closer)

Each function returns a list of at most *n* (tag, score) tuples.
"""
#test
import json, re, string, time, unicodedata
from collections import defaultdict, deque
from pathlib import Path

import requests, lxml.etree as ET
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ───────────────────────────── CONFIG ─────────────────────────────────────
HEADERS   = {"User-Agent": "eng.sultan.fadi@gmail.com (revenue-finder)"}
CIK       = "0000320193"
YEAR_MIN  = 2014
TAXO_YRS  = ("2024", "2023")
CACHE     = Path(".cache"); CACHE.mkdir(exist_ok=True)
FACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"

DOMAIN_SYNS = {"sales": "revenue", "turnover": "revenue"}

# ──────────────────────────── UTILITIES ───────────────────────────────────
def _dl(url: str, fp: Path):
    if fp.exists(): return
    r = requests.get(url, headers=HEADERS, timeout=30); r.raise_for_status()
    fp.write_bytes(r.content); time.sleep(0.25)

def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(f"[{re.escape(string.punctuation)}]", " ", text)
    return " ".join(DOMAIN_SYNS.get(w, w)
                    for w in text.split() if w not in ENGLISH_STOP_WORDS)

# ───────────────────────── TAGS ACTUALLY REPORTED ─────────────────────────
def apple_tags() -> set[str]:
    fp = CACHE / "facts_aapl.json"; _dl(FACTS_URL, fp)
    facts = json.loads(fp.read_bytes())
    reported = set()
    for tag, node in facts["facts"]["us-gaap"].items():
        if tag == "Revenues": continue
        for rows in node["units"].values():
            if any(int(r.get("fy", 0)) >= YEAR_MIN for r in rows):
                reported.add(tag); break
    return reported

# ──────────────────────── LOAD LABEL / DEF TEXTS ──────────────────────────
def pick_year_and_texts():
    ns = {"link": "http://www.xbrl.org/2003/linkbase"}
    for yr in TAXO_YRS:
        base = f"https://xbrl.fasb.org/us-gaap/{yr}/elts"
        lab_fp, doc_fp = CACHE/f"lab_{yr}.xml", CACHE/f"doc_{yr}.xml"
        try:
            _dl(f"{base}/us-gaap-lab-{yr}.xml", lab_fp)
            _dl(f"{base}/us-gaap-doc-{yr}.xml", doc_fp)
        except requests.HTTPError:
            continue

        texts = defaultdict(list)
        for lb in ET.parse(lab_fp).iterfind(".//link:label", ns):
            if lb.get("{http://www.w3.org/1999/xlink}role").endswith("/label"):
                tag = lb.get("{http://www.w3.org/1999/xlink}label").split("_", 1)[-1]
                texts[tag].append(lb.text or "")
        for lb in ET.parse(doc_fp).iterfind(".//link:label", ns):
            if lb.get("{http://www.w3.org/1999/xlink}role").endswith("/documentation"):
                tag = lb.get("{http://www.w3.org/1999/xlink}label").split("_", 1)[-1]
                texts[tag].append(lb.text or "")
        return yr, {k: " ".join(v) for k, v in texts.items()}
    raise RuntimeError("No GAAP taxonomy files downloaded.")

# ─────────────────── PRESENTATION-TREE DEPTHS (clean keys) ───────────────
def presentation_depths(year: str) -> dict[str, int]:
    base = f"https://xbrl.fasb.org/us-gaap/{year}/elts"
    stm_sections = ["is", "bs", "cf", "eq", "ci"]
    urls = ([f"{base}/us-gaap-ent-pre-{year}.xml",
             f"{base}/us-gaap-depcon-pre-{year}.xml"] +
            [f"{base}/us-gaap-stm-{sec}-pre-{year}.xml" for sec in stm_sections])

    ns = {"link": "http://www.xbrl.org/2003/linkbase"}
    children, parents = defaultdict(list), defaultdict(list)

    _local = lambda t: t.split("_", 1)[-1] if "_" in t else t

    for url in urls:
        fp = CACHE / Path(url).name
        try:
            _dl(url, fp)
            root = ET.parse(fp)
            lab_map = {loc.get("{http://www.w3.org/1999/xlink}label"):
                       _local(loc.get("{http://www.w3.org/1999/xlink}href").split("#")[-1])
                       for loc in root.iterfind(".//link:loc", ns)}
            for arc in root.iterfind(".//link:presentationArc", ns):
                p = lab_map.get(arc.get("{http://www.w3.org/1999/xlink}from"))
                c = lab_map.get(arc.get("{http://www.w3.org/1999/xlink}to"))
                if p and c:
                    children[p].append(c); parents[c].append(p)
        except (requests.HTTPError, ET.ParseError):
            continue

    depth, queue = {}, deque((r, 0) for r in children if r not in parents)
    while queue:
        node, d = queue.popleft()
        if node in depth and depth[node] <= d: continue
        depth[node] = d
        queue.extend((ch, d+1) for ch in children.get(node, []))
    return depth

# ──────────────────────── METHOD A : SEMANTIC SIM ────────────────────────
def semantic_similarity(texts: dict[str, str],
                        reported: set[str],
                        target_tag: str,
                        n: int = 5) -> list[tuple[str, float]]:
    corpus, tags = [_normalise(texts[target_tag])], []
    for tag in sorted(reported):
        if tag in texts:
            corpus.append(_normalise(texts[tag])); tags.append(tag)
    vec  = TfidfVectorizer().fit_transform(corpus)
    sims = cosine_similarity(vec[0:1], vec[1:]).ravel()
    ranking = sorted(zip(tags, sims), key=lambda x: x[1], reverse=True)[:n]
    return ranking

# ──────────────── METHOD B : GRANULARITY DIFFERENCE ───────────────────────
def granularity_difference(depths: dict[str, int],
                           reported: set[str],
                           target_tag: str,
                           n: int = 5) -> list[tuple[str, int]]:
    if target_tag in depths:
        ref = depths[target_tag]
    else:
        parts = re.findall(r"[A-Z][a-z0-9]*", target_tag)
        ref = next((depths["".join(parts[:i])]
                    for i in range(len(parts)-1, 0, -1)
                    if "".join(parts[:i]) in depths), None)
        if ref is None:
            ref = sorted(depths.values())[len(depths)//2] if depths else None
    if ref is None:
        return []

    ranked = sorted(((t, abs(depths[t]-ref)) for t in reported if t in depths),
                    key=lambda x: x[1])[:n]
    return ranked

# ───────────────────────────── MAIN DRIVER ───────────────────────────────
def compare_methods(top_n: int = 5):
    year, texts  = pick_year_and_texts()
    reported     = apple_tags()
    target       = ("Revenues" if "Revenues" in texts
                    else "RevenueFromContractWithCustomerExcludingAssessedTax")

    sem_list  = semantic_similarity(texts, reported, target, top_n)
    depths    = presentation_depths(year)
    gran_list = granularity_difference(depths, reported, target, top_n)

    print(f"\nGAAP taxonomy year ➜ {year}")
    print(f"Benchmark tag      ➜ {target}\n")

    print(f"Top {top_n} by SEMANTIC-SIMILARITY (higher = better)")
    for tag, score in sem_list:
        print(f"  {tag:<65}  {score:.3f}")
    print()

    print(f"Top {top_n} by GRANULARITY-DIFFERENCE (lower = better)")
    for tag, gap in gran_list:
        print(f"  {tag:<65}  gap={gap}")
    print()

    return sem_list, gran_list   # lists with scores

if __name__ == "__main__":
    compare_methods(top_n=5)
