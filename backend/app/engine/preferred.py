"""Preferred supplier list (policy section 6). Weights/buckets come from the policy (data), not code."""
from datetime import timedelta
from .util import pdate

DEFAULT_RANKING = {
    "weights": {"frequency": 0.35, "recency": 0.25, "contract": 0.15, "on_time": 0.15, "quality": 0.10},
    "recency_buckets": [[90, 1.0], [365, 0.5]],
}

def _recency(days_since, buckets):
    for limit, score in buckets:
        if days_since <= limit: return score
    return 0.0

def preferred_list(item_code, as_of, ref, params=None):
    params = params or {}
    as_of = pdate(as_of)
    window = params.get("preferred_window_days", 548)
    allowed = set(params.get("allowed_supplier_statuses", ["Active"]))
    rk = params.get("ranking", DEFAULT_RANKING)
    w, buckets = rk["weights"], rk["recency_buckets"]
    start = as_of - timedelta(days=window)

    pos = [p for p in ref["pos_by_item"].get(item_code, []) if start <= p["po_date"] <= as_of]
    contracts = [c for c in ref["contracts_by_item"].get(item_code, []) if c["start"] <= as_of]
    cand = {}
    for p in pos:
        cand.setdefault(p["supplier_id"], {"pos": [], "contracts": []})["pos"].append(p)
    for c in contracts:
        cand.setdefault(c["supplier_id"], {"pos": [], "contracts": []})["contracts"].append(c)

    rows = []
    for sid, d in cand.items():
        s = ref["suppliers"].get(sid)
        if not s or s["status"] not in allowed:   # clause 5.7: blocked / inactive never listed
            continue
        n = len(d["pos"])
        last = max((p["po_date"] for p in d["pos"]), default=None)
        rec = _recency((as_of - last).days, buckets) if last else 0.0
        rows.append({"supplier_id": sid, "name": s["name"], "n_pos": n, "last_po": last, "recency": rec,
                     "contract": 1.0 if d["contracts"] else 0.0,
                     "on_time": s["on_time_pct"], "quality": s["quality_rating"],
                     "_pos": d["pos"], "_contracts": d["contracts"]})
    maxn = max((r["n_pos"] for r in rows), default=0) or 1
    for r in rows:
        r["freq_norm"] = r["n_pos"] / maxn
        r["score"] = round(w["frequency"] * r["freq_norm"] + w["recency"] * r["recency"] + w["contract"] * r["contract"]
                           + w["on_time"] * (r["on_time"] / 100.0) + w["quality"] * (r["quality"] / 5.0), 4)
        # reference price (6.3): latest PO price in window, else latest contract rate
        if r["_pos"]:
            lp = max(r["_pos"], key=lambda p: (p["po_date"], p["po_number"]))
            r["reference_price"], r["ref_source"] = lp["unit_price"], f"PO {lp['po_number']} ({lp['po_date']})"
        else:
            lc = max(r["_contracts"], key=lambda c: (c["start"], c["contract_id"]))
            r["reference_price"], r["ref_source"] = lc["lines"][item_code], f"contract {lc['contract_id']}"
    rows.sort(key=lambda r: (-r["score"], -r["on_time"], -r["quality"], r["supplier_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["why"] = (f"{r['n_pos']} PO(s) in {window}d, recency {r['recency']}, contract {'yes' if r['contract'] else 'no'}, "
                    f"on-time {r['on_time']}%, quality {r['quality']} -> score {r['score']}")
        r.pop("_pos"); r.pop("_contracts")
    return rows

def topup_suppliers(item, preferred, need, ref, params=None):
    """6.4: preferred list in order; if short, add other Active suppliers listing the item's category, best delivery & quality first."""
    allowed = set((params or {}).get("allowed_supplier_statuses", ["Active"]))
    out = [r["supplier_id"] for r in preferred][:need]
    if len(out) < need:
        pool = [s for s in ref["suppliers"].values()
                if s["status"] in allowed and item["category"] in s["categories"] and s["supplier_id"] not in out]
        tw = (params or {}).get("topup_weights", {"on_time": 0.5, "quality": 0.5})
        rec = lambda s: tw["on_time"] * s["on_time_pct"] / 100.0 + tw["quality"] * s["quality_rating"] / 5.0
        pool.sort(key=lambda s: (-rec(s), s["supplier_id"]))
        out += [s["supplier_id"] for s in pool][: need - len(out)]
    return out

def preferred_export(as_of, ref, params=None, top=3):
    rows = []
    for code in sorted(ref["items"]):
        for r in preferred_list(code, as_of, ref, params)[:top]:
            rows.append({"item_code": code, "rank": r["rank"], "supplier_id": r["supplier_id"],
                         "reference_price": r["reference_price"]})
    return rows
