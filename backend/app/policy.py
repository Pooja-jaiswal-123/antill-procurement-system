"""Policy as data: validation, plain-language description, diff, LLM ingestion."""
import json, copy, re
from .engine.util import OPS, describe_cond, pdate

FACT_FIELDS = {"is_new_item", "item_code", "item_type", "category", "plant", "value", "is_emergency", "urgency", "contract_usable",
               "bought_recently", "quantity", "department", "line_count"}
DECISIONS = {"PO", "SOURCING_REQUEST"}
SUPPLIER_MODES = {"contract", "preferred_1", "none"}

def _check_cond(c, errs, where):
    if "all" in c or "any" in c:
        for x in c.get("all", c.get("any")): _check_cond(x, errs, where)
    elif "not" in c: _check_cond(c["not"], errs, where)
    else:
        if c.get("op") not in OPS: errs.append(f"{where}: unknown operator {c.get('op')}")
        if c.get("field") not in FACT_FIELDS: errs.append(f"{where}: unknown field '{c.get('field')}' (known: {', '.join(sorted(FACT_FIELDS))})")
        if "value" not in c: errs.append(f"{where}: missing value")

def validate(p):
    errs = []
    for k in ("version", "effective_date", "params", "rules"):
        if k not in p: errs.append(f"missing '{k}'")
    if errs: return errs
    try: pdate(p["effective_date"])
    except Exception: errs.append("effective_date must be YYYY-MM-DD")
    ids = set()
    for r in p["rules"]:
        w = f"rule {r.get('id')}"
        if r.get("id") in ids: errs.append(f"{w}: duplicate id")
        ids.add(r.get("id"))
        if "when" not in r or "outcome" not in r: errs.append(f"{w}: needs when + outcome"); continue
        _check_cond(r["when"], errs, w)
        o = r["outcome"]
        if o.get("decision") not in DECISIONS: errs.append(f"{w}: decision must be PO or SOURCING_REQUEST")
        if not o.get("route"): errs.append(f"{w}: route missing")
        if o.get("supplier", "none") not in SUPPLIER_MODES: errs.append(f"{w}: supplier must be one of {sorted(SUPPLIER_MODES)}")
        if o.get("decision") == "PO" and o.get("supplier", "none") == "none": errs.append(f"{w}: a PO needs supplier=contract or preferred_1")
    return errs

def describe_rule(r):
    o = r["outcome"]
    sup = {"contract": "contract supplier at contract rate", "preferred_1": "1st preferred supplier at reference price", "none": ""}[o.get("supplier", "none")]
    tail = sup or (f"suggest {o.get('suggest', 0)} suppliers" if o.get("suggest") else "no supplier suggestions")
    return f"[{r['id']}] {r.get('name', '')}: IF {describe_cond(r['when'])} THEN {o['decision']} via {o['route']} ({tail})"

def _flat(d, pre=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict): out.update(_flat(v, f"{pre}{k}."))
        else: out[f"{pre}{k}"] = v
    return out

def diff(old, new):
    ch = []
    if old["version"] != new["version"]: ch.append(f"Version {old['version']} -> {new['version']}")
    if old["effective_date"] != new["effective_date"]: ch.append(f"Effective date {old['effective_date']} -> {new['effective_date']}")
    fo, fn = _flat(old["params"]), _flat(new["params"])
    for k in sorted(set(fo) | set(fn)):
        if fo.get(k) != fn.get(k): ch.append(f"Setting '{k}': {fo.get(k, '(none)')} -> {fn.get(k, '(removed)')}")
    ro, rn = {r["id"]: r for r in old["rules"]}, {r["id"]: r for r in new["rules"]}
    for i, r in rn.items():
        if i not in ro: ch.append("NEW RULE " + describe_rule(r))
        elif json.dumps(ro[i], sort_keys=True) != json.dumps(r, sort_keys=True):
            ch.append("CHANGED RULE " + describe_rule(r) + "   (was: " + describe_rule(ro[i]) + ")")
    for i in ro:
        if i not in rn: ch.append("REMOVED RULE " + describe_rule(ro[i]))
    oo, on = [r["id"] for r in old["rules"] if r["id"] in rn], [r["id"] for r in new["rules"] if r["id"] in ro]
    if oo != on: ch.append("Rule ORDER changed: " + " > ".join(on))
    if json.dumps(old.get("validation"), sort_keys=True) != json.dumps(new.get("validation"), sort_keys=True): ch.append("Validation checks changed")
    return ch or ["No functional change"]

SYSTEM = """You convert procurement policy documents/amendments into a machine-readable policy JSON for a rules engine.
You receive the CURRENT policy JSON and a policy amendment or a described change. Return ONLY the complete NEW policy JSON (no prose, no markdown fences).
Schema rules:
- Top-level keys: policy_id, version (string, bump the current one, e.g. 5.0 -> 5.1, or use the number given in the text), effective_date (YYYY-MM-DD, from the text; if absent use today's date given), currency, params, validation, rules.
- rules are evaluated IN ORDER, first match wins. Each rule: {id, clause, name, when, outcome}.
- when = {"all":[...]} or {"any":[...]} or {"not":{...}} containing leaves {"field","op","value"}.
- fields allowed: is_new_item(bool), item_code, item_type (Material|Service|Capex), category (e.g. "Safety & PPE"), plant (PUN1|CHK1), value (INR number, whole requirement), is_emergency(bool), urgency, contract_usable(bool), bought_recently(bool: bought from an Active supplier within history_days), quantity, department, line_count.
- ops: eq ne lt lte gt gte in not_in contains.
- outcome = {"decision":"PO"|"SOURCING_REQUEST","route":"CONTRACT_PO|EMERGENCY_PO|SPOT_PO|RFQ|RFP|CAPEX_SOURCING|NEW_ITEM_SOURCING (or a new route name)","supplier":"contract"|"preferred_1"|"none","suggest":N}. A PO needs supplier contract or preferred_1; sourcing uses none + suggest count.
- params: history_days, preferred_window_days, allowed_supplier_statuses, clubbing{enabled,created_within_days,need_by_within_days}, consolidation{enabled,within_hours}, valuation_order, ranking{weights,recency_buckets}, topup_weights.
- Keep everything the amendment does not mention EXACTLY as in the current policy. Amounts are in INR (1 lakh = 100000, 1 crore = 10000000).
- A plant-specific or category-specific change is a NEW rule inserted at the correct position in the order (give it a new id like "5.4a"), or a modified condition of an existing rule.
- Blocked/Inactive suppliers are never used: that is enforced by params.allowed_supplier_statuses, keep it.
"""

def llm_draft(text, current, today):
    from . import llm
    out = llm.complete(SYSTEM, f"TODAY: {today}\n\nCURRENT POLICY JSON:\n{json.dumps(current, indent=1)}\n\nAMENDMENT / CHANGE REQUEST:\n{text}", max_tokens=6000)
    out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M).strip()
    return json.loads(out)
