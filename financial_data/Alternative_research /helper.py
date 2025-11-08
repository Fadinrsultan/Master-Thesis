from pathlib import Path
import  re, string, time, unicodedata
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from typing import List

HEADERS      = {"User-Agent": "eng.sultan.fadi@gmail.com (semantic-revenue-finder)"}

def _dl(url: str, fp: Path) -> None:
    """Download-and-cache helper: fetch only if missing; write atomically."""
    if fp.exists():
        return
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    fp.write_bytes(r.content)
    time.sleep(0.25)  # be polite to remote servers
def _normalize(txt: str) -> str:
    """Lowercase, strip punctuation, remove stopwords, canonicalize synonyms."""
    txt = unicodedata.normalize("NFKD", txt).lower()
    txt = re.sub(f"[{re.escape(string.punctuation)}]", " ", txt)
    return " ".join(w for w in txt.split() if w not in ENGLISH_STOP_WORDS)
def _tokenize_positions(text: str) -> List[str]:
    """Normalize + return token list with positions as indices."""
    return _normalize(text).split()
