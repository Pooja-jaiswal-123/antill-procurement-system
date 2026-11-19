"""Deterministic item matcher (policy 1.1). Never invents items: returns candidates from the item master only."""
import re
from difflib import SequenceMatcher

ABBR = {"brg": "bearing", "brgs": "bearing", "hyd": "hydraulic", "pneu": "pneumatic", "rod": "electrode",
        "welding": "welding", "mon": "monitor", "ss": "ss", "vbelt": "v-belt"}
NOISE = {"urgent", "repeat", "sample", "as", "per", "for", "maintenance", "pls", "please", "the", "of", "a", "need", "required", "zz-", "asap"}
SYN = {"rod": "electrode", "zz": "zz", "wheel": "wheel", "monitor": "monitor"}

def norm(text):
    t = (text or "").lower().replace('"', " inch ").replace("-", " ").replace("/", " / ")
    t = re.sub(r"[^a-z0-9./ ]", " ", t)
    toks = []
    for w in t.split():
        w = ABBR.get(w, SYN.get(w, w))
        if w in NOISE: continue
        toks.append(w)
    return toks

def _num_tokens(toks):
    return {t for t in toks if any(ch.isdigit() for ch in t)}

def score(query, item_desc):
    q, d = norm(query), norm(item_desc)
    if not q or not d: return 0.0
    qs, ds = set(q), set(d)
    # numbers/sizes are decisive ("6308" vs "6205")
    qn, dn = _num_tokens(q), _num_tokens(d)
    if qn and dn and not (qn & dn) and not (qn <= dn or dn <= qn): return 0.0
    # token coverage with soft matching (prefix / fuzzy) so "pneu"->"pneumatic" and "brg"->"bearing" work
    def hit(t):
        if t in ds: return 1.0
        best = max((SequenceMatcher(None, t, x).ratio() for x in ds), default=0)
        return best if best >= 0.8 else 0.0
    cov_q = sum(hit(t) for t in q) / len(q)
    cov_d = sum(1.0 if t in qs else (1.0 if any(SequenceMatcher(None, t, x).ratio() >= .8 for x in qs) else 0.0) for t in d) / len(d)
    seq = SequenceMatcher(None, " ".join(q), " ".join(d)).ratio()
    return round(0.45 * cov_q + 0.35 * cov_d + 0.20 * seq, 4)

def candidates(query, items, k=5):
    sc = [(score(query, it["description"]), it) for it in items.values()]
    sc = [(s, it) for s, it in sc if s > 0]
    sc.sort(key=lambda x: -x[0])
    return [{"item_code": it["item_code"], "description": it["description"], "score": s} for s, it in sc[:k]]

AUTO = 0.80      # accept automatically at or above this
MARGIN = 0.08    # and the runner-up must be clearly worse

def match(query, items):
    """returns (item_code|None, confidence, candidates)"""
    c = candidates(query, items)
    if not c: return None, 0.0, c
    top = c[0]
    second = c[1]["score"] if len(c) > 1 else 0.0
    if top["score"] >= AUTO and top["score"] - second >= MARGIN:
        return top["item_code"], top["score"], c
    return None, top["score"], c
