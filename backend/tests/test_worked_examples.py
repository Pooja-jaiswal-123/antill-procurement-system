"""Runs the 14 worked examples from the task kit. Needs the kit data in DATA_DIR (not committed) - skipped otherwise."""
import json, os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
D = os.environ.get("DATA_DIR", "data")
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(D, "sample_pr_batch.csv")), reason="kit data not present")
from app.engine import process, preferred_list
from app.engine.core import build_ref
from app.engine.loader import load_master, load_pdf_contracts, read_batch

WANT = {"PR-26-00019": ("CONTRACT_PO", "S001", 137531), "PR-26-00045": ("CONTRACT_PO", "S021", 26829), "PR-26-00004": ("RFQ", "S014;S013;S016", 220256),
        "PR-26-00034": ("CONTRACT_PO", "S007", 32547), "PR-26-00146": ("SPOT_PO", "S024", 126472), "PR-26-00106": ("SPOT_PO", "S027", 156170),
        "PR-26-00088": ("SPOT_PO", "S023", 97955), "PR-26-00059": ("EMERGENCY_PO", "S014", 253184), "PR-26-00089": ("RFQ", "S043;S044;S042", 336562),
        "PR-26-00050": ("RFQ", "S003;S002;S005", 80300), "PR-26-00100": ("RFP", "S020;S017;S019;S018", 2070780),
        "PR-26-00047": ("CAPEX_SOURCING", "S045;S047;S020;S048;S046", 6036704), "PR-26-00170": ("NEW_ITEM_SOURCING", "", 141100), "PR-26-00035": ("CONTRACT_PO", "S007", 23227)}

@pytest.fixture(scope="module")
def setup():
    items, sup, pos, contracts, plants = load_master(D)
    contracts += load_pdf_contracts(D, {c["contract_id"] for c in contracts})
    ref = build_ref(items, sup, pos, contracts, plants)
    pol = json.load(open("policies/policy_v5_0.json"))
    return ref, pol, process(read_batch(os.path.join(D, "sample_pr_batch.csv")), ref, [pol])

@pytest.mark.parametrize("pr", list(WANT))
def test_example(setup, pr):
    route, sup, val = WANT[pr]
    r = {x["pr_no"]: x for x in setup[2]["rows"]}[pr]
    assert r["route"] == route and (r["supplier_id"] or r["suggested_supplier_ids"]) == sup and abs(float(r["group_value_inr"]) - val) <= 1

def test_hex_bolts_share_one_po(setup):
    r = {x["pr_no"]: x for x in setup[2]["rows"]}
    assert r["PR-26-00034"]["po_id"] == r["PR-26-00035"]["po_id"] == r["PR-26-00031"]["po_id"] and r["PR-26-00034"]["group_id"] == r["PR-26-00032"]["group_id"]

def test_ranking_examples(setup):
    ref, pol, _ = setup
    f = lambda i: [p["supplier_id"] for p in preferred_list(i, "2026-11-01", ref, pol["params"])]
    assert f("ITM-1048") == ["S029", "S030"] and f("ITM-1036") == ["S023", "S022", "S024"] and f("ITM-1016") == ["S009", "S010"]

def test_no_blocked_supplier_anywhere(setup):
    ref, _, res = setup
    bad = {s for s, v in ref["suppliers"].items() if v["status"] != "Active"}
    for r in res["rows"]:
        assert r["supplier_id"] not in bad and not (set(r["suggested_supplier_ids"].split(";")) & bad)
