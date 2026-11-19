import json, os, csv, io
from datetime import date
from . import db
from .engine import process
from .engine.core import build_ref
from .engine.loader import load_master, load_pdf_contracts, read_csv
from .engine.util import pdate, num
from .engine.core import OUT_COLS


def _contract_row(c):
    return (c["contract_id"], c["supplier_id"], str(c["start"]), str(c["end"]), c["cap"], c["consumed"], c.get("source", "register"),
            json.dumps(c["lines"]), c.get("added_by", "seed"), db.now())


def seed_dir(d):
    items, sup, pos, contracts, plants = load_master(d)
    contracts += load_pdf_contracts(d, {c["contract_id"] for c in contracts})
    c = db.conn()

    for t in ("items", "suppliers", "plants", "po_history", "contracts"):
        db.x(f"DELETE FROM {t}")

    db.many("INSERT INTO items VALUES(?,?,?,?,?,?)", [(i["item_code"], i["description"], i["uom"], i["category"], i["item_type"], i["standard_price"]) for i in items])
    db.many("INSERT INTO suppliers VALUES(?,?,?,?,?,?,?)", [(s["supplier_id"], s["name"], s["city"], ";".join(s["categories"]), s["status"], s["on_time_pct"], s["quality_rating"]) for s in sup])
    db.many("INSERT INTO plants VALUES(?,?)", [(p, p) for p in plants])
    db.many("INSERT INTO po_history VALUES(?,?,?,?,?,?,?,?,?)", [(p["po_number"], str(p["po_date"]), p["supplier_id"], p["item_code"], p["quantity"], "", p["unit_price"], p["plant"], int(p["delivered_on_time"])) for p in pos])
    db.many("INSERT INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?)", [_contract_row(c) for c in contracts])

    ensure_default_policy()

    db.audit("system", "seed", "master_data", {"items": len(items), "suppliers": len(sup), "pos": len(pos), "contracts": len(contracts)})
    return {"items": len(items), "suppliers": len(sup), "po_history": len(pos), "contracts": len(contracts), "plants": plants}


def ensure_default_policy():
    if not db.q("SELECT id FROM policies LIMIT 1"):
        policy_path = os.environ.get(
            "DEFAULT_POLICY_PATH",
            os.path.join(os.path.dirname(__file__), "..", "policies", "policy_v5_0.json")
        )

        with open(policy_path, "r", encoding="utf-8") as f:
            p = json.load(f)

        db.x(
            "INSERT INTO policies(version,effective_date,status,body,changes,source,created_by,created_at,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                p["version"],
                p["effective_date"],
                "active",
                json.dumps(p),
                "[]",
                "initial policy v5.0",
                "system",
                db.now(),
                "system",
                db.now()
            )
        )


def load_ref():
    items = db.q("SELECT * FROM items")
    sup = [{**s, "categories": s["categories"].split(";")} for s in db.q("SELECT * FROM suppliers")]
    pos = [{**p, "po_date": pdate(p["po_date"])} for p in db.q("SELECT * FROM po_history")]
    contracts = [{"contract_id": c["contract_id"], "supplier_id": c["supplier_id"], "start": pdate(c["start_date"]), "end": pdate(c["end_date"]),
                  "cap": c["value_cap"], "consumed": c["consumed_value"], "source": c["source"], "lines": json.loads(c["lines"])} for c in db.q("SELECT * FROM contracts")]
    plants = [p["plant"] for p in db.q("SELECT plant FROM plants")]
    return build_ref(items, sup, pos, contracts, plants)


def active_policies():
    out = []
    for r in db.q("SELECT * FROM policies WHERE status='active'"):
        p = json.loads(r["body"])
        p["_created"] = r["approved_at"] or r["created_at"]
        p["_db_id"] = r["id"]
        out.append(p)
    return out


def serialize(res):
    reqs = []
    for r in res["requirements"]:
        reqs.append({"group_id": r["group_id"], "item_code": r["item_code"] or "NEW", "plant": r["plant"], "date": str(r["date"]),
                     "lines": [f"{l['pr_no']}/{l['pr_line']}" for l in r["lines"]], "qty": r["qty"], "value": round(r["value"], 2),
                     "value_src": r.get("value_src", ""), "emergency": r["emergency"], "decision": r.get("decision", ""), "route": r.get("route", ""),
                     "clause": r.get("clause", ""), "policy_version": r["policy"]["version"], "supplier": r.get("supplier"), "price": r.get("price"),
                     "suggested": r.get("suggested", []), "po_id": r.get("po_id", ""), "reason": r.get("reason", ""), "trace": r.get("trace", []),
                     "contracts": r.get("contracts_considered", []),
                     "preferred": [{k: v for k, v in p.items() if k in ("rank", "supplier_id", "name", "score", "reference_price", "ref_source", "why")} for p in r.get("preferred", [])[:5]]})
    return reqs


def run_lines(lines, batch_id=None, actor="system", save=True, only_policy=None):
    ref = load_ref()
    res = process(lines, ref, active_policies(), only_policy=only_policy)
    reqs = serialize(res)

    from collections import Counter
    summ = dict(Counter(r["route"] for r in res["rows"]))
    vers = sorted({r["policy_version"] for r in res["rows"]})
    rid = None

    if save:
        rid = db.x("INSERT INTO runs(batch_id,created_by,created_at,policy_versions,rows,requirements,summary) VALUES(?,?,?,?,?,?,?)",
                   (batch_id, actor, db.now(), json.dumps(vers), json.dumps(res["rows"]), json.dumps(reqs), json.dumps(summ)))
        db.audit(actor, "run_engine", f"run:{rid}", {"batch": batch_id, "lines": len(lines), "policy_versions": vers, "routes": summ})

    return rid, res["rows"], reqs, summ, vers


def batch_lines(batch_id):
    cols = ["pr_no", "pr_line", "created_at", "requester", "department", "plant", "item_code", "description", "quantity", "uom", "estimated_unit_price", "need_by_date", "urgency"]
    return [{c: r[c] for c in cols} for r in db.q("SELECT * FROM pr_lines WHERE batch_id=? ORDER BY id", (batch_id,))]


def add_batch(name, source, rows, actor):
    bid = db.x("INSERT INTO batches(name,source,created_by,created_at) VALUES(?,?,?,?)", (name, source, actor, db.now()))
    db.many("INSERT INTO pr_lines(batch_id,pr_no,pr_line,created_at,requester,department,plant,item_code,description,quantity,uom,estimated_unit_price,need_by_date,urgency) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(bid, r.get("pr_no"), r.get("pr_line", "1"), r.get("created_at"), r.get("requester", ""), r.get("department", ""), r.get("plant"), r.get("item_code", ""),
              r.get("description", ""), r.get("quantity"), r.get("uom", ""), r.get("estimated_unit_price", ""), r.get("need_by_date"), r.get("urgency", "Normal")) for r in rows])
    db.audit(actor, "upload_batch", f"batch:{bid}", {"name": name, "lines": len(rows)})
    return bid


def rows_to_csv(rows):
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=OUT_COLS)
    w.writeheader()

    for r in rows:
        w.writerow({k: r.get(k, "") for k in OUT_COLS})

    return s.getvalue()