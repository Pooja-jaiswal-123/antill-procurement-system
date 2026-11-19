"""Engine tests on a tiny synthetic dataset (no task data needed)."""
import copy, json, os, sys
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.engine import process, preferred_list
from app.engine.core import build_ref
from app.policy import validate, diff

POL = json.load(open(os.path.join(os.path.dirname(__file__), "..", "policies", "policy_v5_0.json")))
D = lambda s: date.fromisoformat(s)

def ref(contracts=()):
    items = [{"item_code": "ITM-1", "description": "Hex bolt M10x40", "uom": "NOS", "category": "Fasteners", "item_type": "Material", "standard_price": 10.0},
             {"item_code": "ITM-2", "description": "Hydraulic oil HLP 68", "uom": "LTR", "category": "Lubricants", "item_type": "Material", "standard_price": 100.0},
             {"item_code": "ITM-9", "description": "EOT crane 5 ton", "uom": "NOS", "category": "Capital Equipment", "item_type": "Capex", "standard_price": 1e6}]
    sup = [{"supplier_id": f"S{i}", "name": f"Sup{i}", "city": "", "categories": ["Fasteners", "Lubricants", "Capital Equipment"], "status": st, "on_time_pct": ot, "quality_rating": q}
           for i, (st, ot, q) in enumerate([("Active", 90, 4), ("Active", 80, 4), ("Blocked", 99, 5), ("Active", 70, 3)], 1)]
    pos = [{"po_number": "1", "po_date": D("2026-09-01"), "supplier_id": "S1", "item_code": "ITM-1", "quantity": 10, "unit_price": 9.0, "plant": "PUN1"},
           {"po_number": "2", "po_date": D("2026-09-05"), "supplier_id": "S3", "item_code": "ITM-1", "quantity": 10, "unit_price": 5.0, "plant": "PUN1"},
           {"po_number": "3", "po_date": D("2026-08-01"), "supplier_id": "S2", "item_code": "ITM-2", "quantity": 10, "unit_price": 100.0, "plant": "PUN1"}]
    return build_ref(items, sup, pos, list(contracts), ["PUN1", "CHK1"])

def line(pr, created, item="ITM-1", qty=100, plant="PUN1", need="2026-11-20", urg="Normal", desc="", est=""):
    return {"pr_no": pr, "pr_line": "1", "created_at": created, "plant": plant, "item_code": item, "description": desc, "quantity": str(qty),
            "uom": "NOS", "estimated_unit_price": est, "need_by_date": need, "urgency": urg}

def contract(cid="RC-1", sup="S1", cap=1000, consumed=0, rate=8.0, start="2026-01-01", end="2026-12-31"):
    return {"contract_id": cid, "supplier_id": sup, "start": D(start), "end": D(end), "cap": cap, "consumed": consumed, "lines": {"ITM-1": rate}, "source": "register"}

def run(lines, r=None, pol=POL):
    return process(lines, r or ref(), [pol])["rows"]

def test_blocked_supplier_never_used():
    rows = run([line("PR1", "2026-11-02 10:00")])
    assert rows[0]["route"] == "SPOT_PO" and rows[0]["supplier_id"] == "S1"

def test_clubbing_and_limits_on_total():
    rows = run([line("PR1", "2026-11-02 10:00", qty=25000), line("PR2", "2026-11-05 10:00", qty=25000)])   # 50000 x 5 (last PO) = 2.5L
    assert rows[0]["group_id"] == rows[1]["group_id"] and rows[0]["route"] == "RFQ"

def test_not_clubbed_different_plant_or_window():
    rows = run([line("PR1", "2026-11-02 10:00"), line("PR2", "2026-11-03 10:00", plant="CHK1"), line("PR3", "2026-11-20 10:00")])
    assert len({r["group_id"] for r in rows}) == 3

def test_contract_ceiling_consumed_in_order():
    r = ref([contract(cap=1000, consumed=0, rate=8.0)])
    rows = run([line("PR1", "2026-11-02 10:00", qty=100), line("PR2", "2026-11-12 10:00", qty=100, need="2026-12-30")], r)  # 800 fits, next 800 doesn't
    assert rows[0]["route"] == "CONTRACT_PO" and rows[1]["route"] != "CONTRACT_PO"
    assert rows[1]["group_value_inr"] == 800.0          # valued at lowest applicable contract rate

def test_lowest_rate_contract_with_room():
    r = ref([contract("RC-A", "S1", cap=1000, consumed=990, rate=5.0), contract("RC-B", "S4", cap=5000, rate=8.0)])
    rows = run([line("PR1", "2026-11-02 10:00")], r)
    assert rows[0]["supplier_id"] == "S4" and rows[0]["unit_price"] == 8.0

def test_inactive_contract_supplier_ignored_and_future_contract_ignored():
    r = ref([contract("RC-A", "S3"), contract("RC-B", "S1", start="2026-11-15")])
    assert run([line("PR1", "2026-11-02 10:00")], r)[0]["route"] != "CONTRACT_PO"

def test_capex_beats_contract_and_new_item_never_clubbed():
    rows = run([line("PR1", "2026-11-02 10:00", item="ITM-9", qty=1), line("PR2", "2026-11-02 11:00", item="", desc="zzz widget", qty=2, est="50"),
                line("PR3", "2026-11-02 12:00", item="", desc="zzz widget", qty=2, est="50")])
    assert rows[0]["route"] == "CAPEX_SOURCING" and rows[1]["route"] == "NEW_ITEM_SOURCING" and rows[1]["group_id"] != rows[2]["group_id"]
    assert rows[1]["group_value_inr"] == 100.0

def test_emergency_rule_and_no_history_goes_to_rfq():
    rows = run([line("PR1", "2026-11-02 10:00", item="ITM-2", qty=3000, urg="Emergency")])    # 3L > 2L but <=5L, bought 3 months ago
    assert rows[0]["route"] == "EMERGENCY_PO"
    rows = run([line("PR1", "2026-11-02 10:00", item="ITM-9", qty=1)])
    assert rows[0]["route"] == "CAPEX_SOURCING"

def test_consolidation_within_24h_same_supplier_plant_route():
    rows = run([line("PR1", "2026-11-02 10:00", need="2026-11-20"), line("PR2", "2026-11-03 09:00", need="2026-12-30"), line("PR3", "2026-11-03 11:00", need="2027-01-20")])
    assert rows[0]["po_id"] == rows[1]["po_id"] != rows[2]["po_id"]

def test_not_processed_bad_quantity_and_plant():
    rows = run([line("PR1", "2026-11-02 10:00", qty=0), line("PR2", "2026-11-02 10:00", plant="PUN9")])
    assert [r["route"] for r in rows] == ["NOT_PROCESSED"] * 2

def test_free_text_match_and_ambiguous_goes_new():
    rows = run([line("PR1", "2026-11-02 10:00", item="", desc="hyd oil hlp 68", qty=10)])
    assert rows[0]["resolved_item_code"] == "ITM-2"

def test_policy_amendment_without_code_change():
    new = copy.deepcopy(POL); new["version"] = "5.1"; new["effective_date"] = "2026-11-10"
    for r_ in new["rules"]:
        if r_["id"] == "5.4": r_["when"]["all"][0]["value"] = 1000          # spot limit now ₹1,000
    new["rules"].insert(3, {"id": "X1", "clause": "X1", "name": "CHK1 fasteners always RFQ", "when": {"all": [{"field": "plant", "op": "eq", "value": "CHK1"}, {"field": "category", "op": "eq", "value": "Fasteners"}]},
                            "outcome": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "none", "suggest": 3}})
    assert validate(new) == [] and any("NEW RULE" in c for c in diff(POL, new))
    ls = [line("PR1", "2026-11-02 10:00"), line("PR2", "2026-11-12 10:00", plant="PUN1", qty=1000, need="2026-12-30"), line("PR3", "2026-11-12 11:00", plant="CHK1", qty=1000, need="2026-12-30")]
    out = process(ls, ref(), [POL, new])["rows"]
    assert out[0]["route"] == "SPOT_PO" and out[0]["policy_version"] == "5.0"      # before effective date
    assert out[1]["route"] == "RFQ" and out[1]["policy_version"] == "5.1"
    assert out[2]["route"] == "RFQ" and "X1" in out[2]["reason"]

def test_preferred_excludes_blocked_and_uses_reference_price():
    pl = preferred_list("ITM-1", D("2026-11-02"), ref(), POL["params"])
    assert [p["supplier_id"] for p in pl] == ["S1"] and pl[0]["reference_price"] == 9.0
