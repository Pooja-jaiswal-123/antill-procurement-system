"""Policy-driven PR -> PO decision engine. Pure python: no web, no DB. Everything rule-like comes from the policy JSON."""
from datetime import timedelta
from .util import pdate, pdt, num, eval_cond, describe_cond
from .preferred import preferred_list, topup_suppliers
from . import matcher

OUT_COLS = ["pr_no", "pr_line", "resolved_item_code", "group_id", "po_id", "decision", "route", "supplier_id", "unit_price",
            "group_value_inr", "suggested_supplier_ids", "policy_version", "reason"]

def active_policy(policies, on_date):
    """Latest approved policy whose effective date <= on_date (else the earliest, so nothing is ever policy-less)."""
    on_date = pdate(on_date)
    ok = [p for p in policies if pdate(p["effective_date"]) <= on_date]
    if ok: return max(ok, key=lambda p: (pdate(p["effective_date"]), p.get("_created", "")))
    return min(policies, key=lambda p: pdate(p["effective_date"]))

def build_ref(items, suppliers, pos, contracts, plants):
    """Index master data (lists of dicts with python dates) for fast lookup."""
    ref = {"items": {i["item_code"]: i for i in items}, "suppliers": {s["supplier_id"]: s for s in suppliers},
           "plants": set(plants), "contracts": contracts, "pos_by_item": {}, "contracts_by_item": {}}
    for p in pos: ref["pos_by_item"].setdefault(p["item_code"], []).append(p)
    for c in contracts:
        for code in c["lines"]: ref["contracts_by_item"].setdefault(code, []).append(c)
    return ref

# ---------------------------------------------------------------- helpers
def _resolve_item(line, ref):
    code = (line.get("item_code") or "").strip()
    if code and code in ref["items"]:
        return code, "item code given", []
    note = f"item code {code} not in item master; " if code else ""
    found, conf, cands = matcher.match(line.get("description", ""), ref["items"])
    if found:
        return found, f"{note}free text matched ({conf:.2f})", cands
    hint = ""
    if cands and cands[0]["score"] >= 0.55:
        hint = " closest: " + ", ".join(f"{c['item_code']} ({c['score']:.2f})" for c in cands[:3]) + " - too ambiguous to auto-match"
    return None, f"{note}no confident item master match.{hint}", cands

def _contracts_for(item_code, req_date, ref, params):
    allowed = set(params.get("allowed_supplier_statuses", ["Active"]))
    out = []
    for c in ref["contracts_by_item"].get(item_code, []):
        s = ref["suppliers"].get(c["supplier_id"])
        if c["start"] <= req_date <= c["end"] and s and s["status"] in allowed:
            out.append(c)
    return out

def _last_po(item_code, req_date, ref, days):
    lo = req_date - timedelta(days=days)
    pos = [p for p in ref["pos_by_item"].get(item_code, []) if lo <= p["po_date"] < req_date + timedelta(days=0) or p["po_date"] == req_date]
    pos = [p for p in pos if lo <= p["po_date"] <= req_date]
    return max(pos, key=lambda p: (p["po_date"], p["po_number"])) if pos else None

def _bought_recently(item_code, req_date, ref, params):
    allowed = set(params.get("allowed_supplier_statuses", ["Active"]))
    lo = req_date - timedelta(days=params.get("history_days", 365))
    return [p for p in ref["pos_by_item"].get(item_code, [])
            if lo <= p["po_date"] <= req_date and ref["suppliers"].get(p["supplier_id"], {}).get("status") in allowed]

def _fmt(v): return f"{v:,.2f}"

# ---------------------------------------------------------------- main
def process(lines, ref, policies, only_policy=None):
    """lines: list of raw PR line dicts. Returns {'rows','requirements','pos','consumed'}."""
    L = []
    for i, raw in enumerate(lines):
        l = dict(raw)
        l["_idx"] = i
        l["_created"] = pdt(l["created_at"])
        l["_need"] = pdate(l["need_by_date"]) if str(l.get("need_by_date") or "").strip() else None
        l["_qty"] = num(l.get("quantity"))
        l["_est"] = num(l.get("estimated_unit_price"))
        l["_line"] = int(num(l.get("pr_line")) or 0)
        L.append(l)
    pol_of = lambda d: only_policy or active_policy(policies, d)

    # 1. item resolution + validation
    rows_by_idx, valid = {}, []
    for l in L:
        code, how, cands = _resolve_item(l, ref)
        l["_item"], l["_how"], l["_cands"] = code, how, cands
        pol = pol_of(l["_created"].date())
        l["_pol"] = pol
        facts = {"quantity": l["_qty"], "plant_known": (l.get("plant") or "") in ref["plants"]}
        bad = [v["message"] for v in pol.get("validation", []) if not eval_cond(v, facts)]
        if l["_need"] is None: bad.append("Need-by date missing")
        if bad:
            rows_by_idx[l["_idx"]] = {"pr_no": l["pr_no"], "pr_line": l["pr_line"], "resolved_item_code": code or "NEW", "group_id": "",
                                      "po_id": "", "decision": "", "route": "NOT_PROCESSED", "supplier_id": "", "unit_price": "",
                                      "group_value_inr": "", "suggested_supplier_ids": "", "policy_version": pol["version"],
                                      "reason": "NOT_PROCESSED: " + "; ".join(bad) + " - returned to requester for correction"}
        else:
            valid.append(l)

    # 2. clubbing (clause 2.2) - lines in creation order, join the earliest eligible requirement
    valid.sort(key=lambda l: (l["_created"], l["pr_no"], l["_line"]))
    reqs = []
    for l in valid:
        cp = l["_pol"]["params"].get("clubbing", {"enabled": True, "created_within_days": 14, "need_by_within_days": 7})
        home = None
        if l["_item"] and cp.get("enabled", True):
            for r in reqs:
                if r["item_code"] == l["_item"] and r["plant"] == l["plant"]:
                    if (l["_created"].date() - r["first"]["_created"].date()).days <= cp["created_within_days"] and \
                       abs((l["_need"] - r["first"]["_need"]).days) <= cp["need_by_within_days"]:
                        home = r; break
        if home: home["lines"].append(l)
        else: reqs.append({"item_code": l["_item"], "plant": l["plant"], "first": l, "lines": [l]})

    # 3. decide requirements in creation order (ceiling consumption order, clause 4.2)
    consumed = {c["contract_id"]: c["consumed"] for c in ref["contracts"]}
    for n, r in enumerate(reqs, 1):
        r["group_id"] = f"REQ-{n:04d}"
        f = r["first"]; r["date"] = f["_created"].date(); r["dt"] = f["_created"]
        pol = f["_pol"]; P = pol["params"]; r["policy"] = pol
        r["qty"] = sum(x["_qty"] for x in r["lines"])
        r["emergency"] = any(str(x.get("urgency", "")).strip().lower() == "emergency" for x in r["lines"])
        code = r["item_code"]; item = ref["items"].get(code)
        notes, trace = [], []
        contract, cand_info, value, price_src = None, [], 0.0, ""
        if item:
            applicable = _contracts_for(code, r["date"], ref, P)
            usable = []
            for c in applicable:
                rate = c["lines"][code]; need = r["qty"] * rate
                room = c["cap"] - consumed[c["contract_id"]]
                ok = consumed[c["contract_id"]] + need <= c["cap"] + 1e-9
                cand_info.append({"contract_id": c["contract_id"], "supplier_id": c["supplier_id"], "rate": rate,
                                  "ceiling_left": round(room, 2), "fits": ok})
                if ok: usable.append((rate, c["contract_id"], c))
            if usable:
                contract = min(usable, key=lambda x: (x[0], x[1]))[2]
            # valuation (3.1): order is policy data
            for src in P.get("valuation_order", ["contract_rate", "last_po_price", "standard_price"]):
                if src == "contract_rate" and applicable:
                    c = contract or min(applicable, key=lambda c: (c["lines"][code], c["contract_id"]))
                    unit = c["lines"][code]
                    price_src = f"contract {c['contract_id']} rate" + ("" if contract else " (lowest applicable; all out of ceiling)"); break
                if src == "last_po_price":
                    lp = _last_po(code, r["date"], ref, P.get("history_days", 365))
                    if lp: unit = lp["unit_price"]; price_src = f"last PO {lp['po_number']} ({lp['po_date']}, {lp['supplier_id']})"; break
                if src == "standard_price":
                    unit = item["standard_price"]; price_src = "item master standard price"; break
            value = r["qty"] * unit
            r["unit_val"] = unit
        else:
            est = f["_est"]
            if est is None: notes.append("requester gave no estimated price - value unknown, routed to sourcing regardless")
            value = r["qty"] * (est or 0.0); price_src = "requester estimate"; r["unit_val"] = est or 0.0
        r["value"] = value; r["value_src"] = price_src

        bought = _bought_recently(code, r["date"], ref, P) if item else []
        pref = preferred_list(code, r["date"], ref, P) if item else []
        facts = {"is_new_item": item is None, "item_code": code or "NEW", "item_type": item["item_type"] if item else "",
                 "category": item["category"] if item else "", "plant": r["plant"], "value": value,
                 "is_emergency": r["emergency"], "urgency": "Emergency" if r["emergency"] else "Normal",
                 "contract_usable": contract is not None, "bought_recently": bool(bought),
                 "quantity": r["qty"], "department": f.get("department", ""), "line_count": len(r["lines"])}
        r["facts"] = facts

        chosen = None
        for rule in pol["rules"]:
            hit = eval_cond(rule["when"], facts)
            o = rule["outcome"]
            if hit and o.get("supplier") == "preferred_1" and not pref:
                trace.append(f"{rule['id']} matched but no Active preferred supplier -> skipped (5.7)"); continue
            if hit and o.get("supplier") == "contract" and not contract:
                trace.append(f"{rule['id']} skipped: no contract"); continue
            trace.append(f"{rule['id']} {'MATCH' if hit else 'no'}: {describe_cond(rule['when'])}")
            if hit: chosen = rule; break
        r["trace"] = trace; r["contracts_considered"] = cand_info; r["preferred"] = pref
        if not chosen:
            r.update(decision="", route="NOT_PROCESSED", supplier=None, price=None, suggested=[], clause="-",
                     reason="NOT_PROCESSED: no policy rule matched this requirement"); continue
        o = chosen["outcome"]
        r["clause"] = chosen["clause"]; r["rule"] = chosen; r["decision"] = o["decision"]; r["route"] = o["route"]
        r["supplier"], r["price"], r["suggested"], relied = None, None, [], ""
        if o.get("supplier") == "contract":
            r["supplier"], r["price"] = contract["supplier_id"], contract["lines"][code]
            relied = f"contract {contract['contract_id']} (supplier {contract['supplier_id']}, ceiling left before this req ₹{_fmt(contract['cap'] - consumed[contract['contract_id']])})"
            consumed[contract["contract_id"]] += value
            r["relied"] = contract["contract_id"]
        elif o.get("supplier") == "preferred_1":
            top = pref[0]; r["supplier"], r["price"] = top["supplier_id"], top["reference_price"]
            relied = f"1st preferred supplier {top['supplier_id']} - {top['ref_source']}"
            r["relied"] = top["ref_source"]
        n_sug = int(o.get("suggest", 0) or 0)
        if n_sug and item:
            r["suggested"] = topup_suppliers(item, pref, n_sug, ref, P)
            relied = "suggested from preferred list" + (" + category top-up" if len(pref) < n_sug else "")
        if o["route"] == "CONTRACT_PO" and False: pass
        skipped = [c for c in cand_info if not c["fits"]]
        if skipped and not contract:
            notes.append("contract(s) out of ceiling: " + ", ".join(f"{c['contract_id']} (left ₹{_fmt(c['ceiling_left'])})" for c in skipped))
        if skipped and contract:
            notes.append("cheaper/other contract skipped for ceiling: " + ", ".join(c["contract_id"] for c in skipped))
        if f["_pol"] and item is None: notes.append(f["_how"])
        if len(r["lines"]) > 1: notes.append(f"{len(r['lines'])} PR lines clubbed (cl.2.2)")
        r["reason"] = (f"Policy v{pol['version']} cl.{chosen['clause']} ({chosen['name']}); value ₹{_fmt(value)} from {price_src}"
                       + (f"; {relied}" if relied else "") + ("; " + "; ".join(notes) if notes else ""))

    # 4. consolidation into POs (clause 7)
    pos = []
    for r in reqs:
        if r.get("decision") != "PO": r["po_id"] = ""; continue
        C = r["policy"]["params"].get("consolidation", {"enabled": True, "within_hours": 24})
        home = None
        if C.get("enabled", True):
            for po in pos:
                if po["supplier"] == r["supplier"] and po["plant"] == r["plant"] and po["route"] == r["route"] and \
                   (r["dt"] - po["anchor"]).total_seconds() <= C["within_hours"] * 3600:
                    home = po; break
        if not home:
            home = {"po_id": f"PO-{len(pos) + 1:04d}", "supplier": r["supplier"], "plant": r["plant"], "route": r["route"],
                    "anchor": r["dt"], "reqs": []}
            pos.append(home)
        home["reqs"].append(r); r["po_id"] = home["po_id"]
        if len(home["reqs"]) > 1: r["reason"] += f"; consolidated into {home['po_id']} (cl.7.1)"

    # 5. rows per PR line
    for r in reqs:
        for l in r["lines"]:
            rows_by_idx[l["_idx"]] = {
                "pr_no": l["pr_no"], "pr_line": l["pr_line"], "resolved_item_code": r["item_code"] or "NEW",
                "group_id": r["group_id"], "po_id": r.get("po_id", ""), "decision": r.get("decision", ""), "route": r.get("route", ""),
                "supplier_id": r.get("supplier") or "", "unit_price": "" if r.get("price") is None else round(r["price"], 2),
                "group_value_inr": round(r["value"], 2), "suggested_supplier_ids": ";".join(r.get("suggested", [])),
                "policy_version": r["policy"]["version"], "reason": r.get("reason", "")}
    rows = [rows_by_idx[i] for i in range(len(L))]
    return {"rows": rows, "requirements": reqs, "pos": pos, "consumed": consumed}
