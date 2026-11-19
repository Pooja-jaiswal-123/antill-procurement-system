import os, io, csv, json
from datetime import date
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from . import db, services, chat, policy as pol, llm
from .engine import preferred_export, preferred_list
from .engine.util import pdate
from .contract_pdf import parse_contract_pdf

app = FastAPI(title="Corvo PR-to-PO API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
DATA_DIR = os.environ.get("DATA_DIR", "data")

@app.on_event("startup")
def startup():
    db.conn()
    from .engine.loader import find
    if not db.q("SELECT 1 FROM items LIMIT 1") and os.path.isdir(DATA_DIR) and find(DATA_DIR, "item_master.csv"):
        try: services.seed_dir(DATA_DIR)
        except Exception as e:
            uploaded = ", ".join(sorted(os.path.basename(f) for f in os.listdir(DATA_DIR)))
            raise HTTPException(400, f"Could not load master data: {e}. Uploaded files: {uploaded}. Required CSVs: item_master, supplier_master, po_history, plants, contract_register, contract_lines")
    services.ensure_default_policy()

def who(x): return (x or "buyer").strip()[:40]

@app.get("/api/health")
def health(): return {"ok": True, "llm": llm.available(), "model": llm.MODEL}

@app.get("/api/state")
def state():
    c = lambda t: db.q(f"SELECT COUNT(*) c FROM {t}")[0]["c"]
    return {"items": c("items"), "suppliers": c("suppliers"), "po_history": c("po_history"), "contracts": c("contracts"),
            "batches": c("batches"), "runs": c("runs"), "llm": llm.available(), "data_loaded": c("items") > 0}

# ------------------------------------------------------------- master data
@app.post("/api/admin/load-data")
async def load_data(files: list[UploadFile] = File(...), x_user: str = Header(None)):
    import tempfile
    d = tempfile.mkdtemp()
    for f in files:
        with open(os.path.join(d, os.path.basename(f.filename)), "wb") as o: o.write(await f.read())
    try: res = services.seed_dir(d)
    except Exception as e:
        uploaded = ", ".join(sorted(os.path.basename(f) for f in os.listdir(d)))
        raise HTTPException(400, f"Could not load master data: {e}. Uploaded files: {uploaded}. Required CSVs: item_master, supplier_master, po_history, plants, contract_register, contract_lines")
    return res

@app.get("/api/items")
def items(): return db.q("SELECT * FROM items ORDER BY item_code")

@app.get("/api/suppliers")
def suppliers(): return db.q("SELECT * FROM suppliers ORDER BY supplier_id")

# ------------------------------------------------------------- batch processing
def _parse_csv(raw: bytes):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    need = {"pr_no", "pr_line", "created_at", "plant", "quantity", "need_by_date", "urgency"}
    if not rows or not need <= set(rows[0].keys()): raise HTTPException(400, f"CSV must have columns: {', '.join(sorted(need))}, item_code, description, uom, estimated_unit_price")
    return rows

@app.post("/api/process-batch")
async def process_batch(file: UploadFile = File(...), format: str = Query("json"), save: bool = Query(False), policy_version: str = Query(None), x_user: str = Header(None)):
    """Stateless by default: returns decisions for the uploaded batch. save=true also stores batch+run for the buyer workspace."""
    rows = _parse_csv(await file.read())
    only = None
    if policy_version:
        m = [json.loads(p["body"]) for p in db.q("SELECT body FROM policies WHERE version=?", (policy_version,))]
        if not m: raise HTTPException(404, "unknown policy version")
        only = m[0]
    bid = services.add_batch(file.filename, "api", rows, who(x_user)) if save else None
    rid, out, reqs, summ, vers = services.run_lines(rows, bid, who(x_user), save=save, only_policy=only)
    if format == "csv": return PlainTextResponse(services.rows_to_csv(out), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=decisions.csv"})
    return {"run_id": rid, "batch_id": bid, "policy_versions": vers, "summary": summ, "decisions": out}

@app.post("/api/batches")
async def upload_batch(file: UploadFile = File(...), x_user: str = Header(None)):
    rows = _parse_csv(await file.read())
    bid = services.add_batch(file.filename, "upload", rows, who(x_user))
    rid, out, reqs, summ, vers = services.run_lines(rows, bid, who(x_user))
    return {"batch_id": bid, "run_id": rid, "summary": summ, "policy_versions": vers}

@app.get("/api/batches")
def batches():
    return db.q("SELECT b.*, (SELECT COUNT(*) FROM pr_lines WHERE batch_id=b.id) lines, (SELECT MAX(id) FROM runs WHERE batch_id=b.id) last_run FROM batches b ORDER BY id DESC")

@app.post("/api/batches/{bid}/reprocess")
def reprocess(bid: int, x_user: str = Header(None)):
    lines = services.batch_lines(bid)
    if not lines: raise HTTPException(404, "empty or unknown batch")
    rid, out, reqs, summ, vers = services.run_lines(lines, bid, who(x_user))
    return {"batch_id": bid, "run_id": rid, "summary": summ, "policy_versions": vers}

def _run(rid):
    r = db.q("SELECT * FROM runs WHERE id=?", (rid,))
    if not r: raise HTTPException(404, "run not found")
    return r[0]

@app.get("/api/runs/{rid}")
def get_run(rid: int):
    r = _run(rid)
    acts = db.q("SELECT * FROM actions WHERE run_id=? ORDER BY id", (rid,))
    status = {}
    for a in acts: status[a["group_id"]] = {"kind": a["kind"], "comment": a["comment"], "actor": a["actor"], "at": a["at"], "payload": json.loads(a["payload"] or "{}")}
    return {"id": rid, "batch_id": r["batch_id"], "created_at": r["created_at"], "policy_versions": json.loads(r["policy_versions"]),
            "summary": json.loads(r["summary"]), "requirements": json.loads(r["requirements"]), "rows": json.loads(r["rows"]), "status": status}

@app.get("/api/runs/{rid}/export.csv")
def export_run(rid: int):
    return PlainTextResponse(services.rows_to_csv(json.loads(_run(rid)["rows"])), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=decisions_run{rid}.csv"})

@app.get("/api/runs")
def runs(): return db.q("SELECT id,batch_id,created_by,created_at,policy_versions,summary FROM runs ORDER BY id DESC LIMIT 50")

def _req(rid, gid):
    reqs = json.loads(_run(rid)["requirements"])
    m = [r for r in reqs if r["group_id"] == gid]
    if not m: raise HTTPException(404, "requirement not found")
    return m[0]

@app.post("/api/runs/{rid}/requirements/{gid}/approve")
def approve(rid: int, gid: str, x_user: str = Header(None)):
    r = _req(rid, gid)
    if db.q("SELECT id FROM actions WHERE run_id=? AND group_id=?", (rid, gid)): raise HTTPException(409, "already actioned")
    if r["route"] == "NOT_PROCESSED": raise HTTPException(400, "nothing to approve - fix the PR and reprocess")
    n = db.q("SELECT COUNT(*) c FROM actions WHERE kind IN ('approve','override') AND payload LIKE ?", (f'%"doc":"{r["route"]}%',))[0]["c"]
    doc = r["po_id"] if r["decision"] == "PO" else f"{r['route']}-{rid}-{gid[-4:]}"
    db.x("INSERT INTO actions(run_id,group_id,kind,comment,payload,actor,at) VALUES(?,?,?,?,?,?,?)", (rid, gid, "approve", "", json.dumps({"doc": doc, "route": r["route"]}), who(x_user), db.now()))
    db.audit(who(x_user), "approve", f"run:{rid}/{gid}", {"created": doc, "route": r["route"], "clause": r["clause"], "policy_version": r["policy_version"]})
    return {"created": doc, "kind": "PO" if r["decision"] == "PO" else r["route"]}

@app.post("/api/runs/{rid}/requirements/{gid}/override")
def override(rid: int, gid: str, body: dict, x_user: str = Header(None)):
    comment = (body.get("comment") or "").strip()
    if len(comment) < 5: raise HTTPException(400, "An override needs a written reason (comment).")
    r = _req(rid, gid)
    if db.q("SELECT id FROM actions WHERE run_id=? AND group_id=?", (rid, gid)): raise HTTPException(409, "already actioned")
    new = {"route": body.get("route") or r["route"], "supplier_id": body.get("supplier_id") or r["supplier"]}
    sup = db.q("SELECT status FROM suppliers WHERE supplier_id=?", (new["supplier_id"],)) if new["supplier_id"] else []
    if new["supplier_id"] and (not sup or sup[0]["status"] != "Active"): raise HTTPException(400, "Blocked/inactive/unknown suppliers can never be used (clause 5.7).")
    payload = {"original": {"route": r["route"], "supplier": r["supplier"], "clause": r["clause"], "policy_version": r["policy_version"]}, "new": new}
    db.x("INSERT INTO actions(run_id,group_id,kind,comment,payload,actor,at) VALUES(?,?,?,?,?,?,?)", (rid, gid, "override", comment, json.dumps(payload), who(x_user), db.now()))
    db.audit(who(x_user), "override", f"run:{rid}/{gid}", {**payload, "comment": comment})
    return {"ok": True}

# ------------------------------------------------------------- preferred suppliers
def _policy_params(as_of):
    from .engine import active_policy
    return active_policy(services.active_policies(), as_of)["params"]

@app.get("/api/preferred-suppliers.csv")
def preferred_csv(as_of: str = Query(...), top: int = 3):
    rows = preferred_export(pdate(as_of), services.load_ref(), _policy_params(as_of), top)
    s = io.StringIO(); w = csv.DictWriter(s, fieldnames=["item_code", "rank", "supplier_id", "reference_price"]); w.writeheader(); w.writerows(rows)
    return PlainTextResponse(s.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=preferred_{as_of}.csv"})

@app.get("/api/preferred-suppliers/{item_code}")
def preferred_item(item_code: str, as_of: str = Query(None)):
    as_of = as_of or date.today().isoformat()
    return preferred_list(item_code, pdate(as_of), services.load_ref(), _policy_params(as_of))

# ------------------------------------------------------------- policy
@app.get("/api/policies")
def policies():
    out = db.q("SELECT id,version,effective_date,status,changes,source,created_by,created_at,approved_by,approved_at FROM policies ORDER BY effective_date DESC, id DESC")
    for p in out: p["changes"] = json.loads(p["changes"] or "[]")
    return out

@app.get("/api/policies/{pid}")
def policy_get(pid: int):
    r = db.q("SELECT * FROM policies WHERE id=?", (pid,))
    if not r: raise HTTPException(404)
    return {**r[0], "body": json.loads(r[0]["body"]), "changes": json.loads(r[0]["changes"] or "[]"), "rules_text": [pol.describe_rule(x) for x in json.loads(r[0]["body"])["rules"]]}

def _current():
    ps = services.active_policies()
    from .engine import active_policy
    return active_policy(ps, date.today())

@app.post("/api/policies/draft")
async def policy_draft(text: str = Form(None), file: UploadFile = File(None), policy_json: str = Form(None), x_user: str = Header(None)):
    """Upload an amendment document (PDF/txt), describe a change in text, or paste full policy JSON -> returns a DRAFT with plain-language diff."""
    cur = _current(); cur = {k: v for k, v in cur.items() if not k.startswith("_")}
    src = "text"
    if policy_json:
        try: new = json.loads(policy_json)
        except Exception as e: raise HTTPException(400, f"Invalid JSON: {e}")
        src = "policy JSON"
    else:
        if file is not None and file.filename:
            raw = await file.read(); src = file.filename
            if file.filename.lower().endswith(".pdf"):
                from pypdf import PdfReader
                text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
            elif file.filename.lower().endswith(".json"):
                try: new = json.loads(raw.decode()); text = None
                except Exception as e: raise HTTPException(400, f"Invalid JSON file: {e}")
            else: text = raw.decode("utf-8", "ignore")
        if text:
            if not llm.available(): raise HTTPException(503, "Reading a policy document needs the Groq API (set GROQ_API_KEY). Alternatively paste/upload full policy JSON.")
            try: new = pol.llm_draft(text, cur, date.today().isoformat())
            except Exception as e: raise HTTPException(502, f"Could not read the amendment: {e}")
        elif "new" not in locals(): raise HTTPException(400, "Provide a document, a description, or policy JSON")
    new = {k: v for k, v in new.items() if not k.startswith("_")}
    existing = {p["version"] for p in db.q("SELECT version FROM policies")}
    v = str(new.get("version", "")); base = v
    while v in existing or not v:
        try: v = f"{float(v or cur['version']) + 0.1:.1f}"
        except ValueError: v = v + ".1"
    new["version"] = v
    errs = pol.validate(new)
    changes = pol.diff(cur, new) if not errs else []
    pid = db.x("INSERT INTO policies(version,effective_date,status,body,changes,source,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (v, new.get("effective_date", ""), "draft" if not errs else "invalid", json.dumps(new), json.dumps(changes), src, who(x_user), db.now()))
    db.audit(who(x_user), "policy_draft", f"policy:{pid}", {"version": v, "source": src, "errors": errs})
    return {"id": pid, "version": v, "effective_date": new.get("effective_date"), "errors": errs, "changes": changes, "status": "draft" if not errs else "invalid"}

@app.post("/api/policies/{pid}/approve")
def policy_approve(pid: int, body: dict = None, x_user: str = Header(None)):
    r = db.q("SELECT * FROM policies WHERE id=?", (pid,))
    if not r or r[0]["status"] != "draft": raise HTTPException(400, "Only a valid draft can be approved")
    p = json.loads(r[0]["body"])
    if body and body.get("effective_date"): p["effective_date"] = body["effective_date"]
    errs = pol.validate(p)
    if errs: raise HTTPException(400, "; ".join(errs))
    db.x("UPDATE policies SET status='active', body=?, effective_date=?, approved_by=?, approved_at=? WHERE id=?", (json.dumps(p), p["effective_date"], who(x_user), db.now(), pid))
    db.audit(who(x_user), "policy_approve", f"policy:{pid}", {"version": p["version"], "effective_date": p["effective_date"]})
    return {"ok": True, "version": p["version"], "effective_date": p["effective_date"]}

@app.post("/api/policies/{pid}/reject")
def policy_reject(pid: int, x_user: str = Header(None)):
    db.x("UPDATE policies SET status='rejected' WHERE id=? AND status IN ('draft','invalid')", (pid,))
    db.audit(who(x_user), "policy_reject", f"policy:{pid}"); return {"ok": True}

# ------------------------------------------------------------- contracts
@app.get("/api/contracts")
def contracts():
    out = db.q("SELECT * FROM contracts ORDER BY contract_id")
    names = {s["supplier_id"]: s for s in db.q("SELECT * FROM suppliers")}
    for c in out:
        c["lines"] = json.loads(c["lines"]); s = names.get(c["supplier_id"], {}); c["supplier_name"] = s.get("name"); c["supplier_status"] = s.get("status")
    return out

def _save_contract(c, actor):
    if db.q("SELECT 1 FROM contracts WHERE contract_id=?", (c["contract_id"],)): raise HTTPException(409, f"{c['contract_id']} already exists")
    s = db.q("SELECT status FROM suppliers WHERE supplier_id=?", (c["supplier_id"],))
    if not s: raise HTTPException(400, f"unknown supplier {c['supplier_id']}")
    bad = [i for i in c["lines"] if not db.q("SELECT 1 FROM items WHERE item_code=?", (i,))]
    if bad: raise HTTPException(400, f"unknown items in contract: {bad}")
    c["added_by"] = actor; c["source"] = c.get("source", "manual")
    db.x("INSERT INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?)", services._contract_row(c))
    db.audit(actor, "add_contract", f"contract:{c['contract_id']}", {"source": c["source"], "supplier": c["supplier_id"], "lines": len(c["lines"])})

@app.post("/api/contracts/extract")
async def contract_extract(file: UploadFile = File(...), confirm: bool = Query(False), x_user: str = Header(None)):
    """Extract a PDF-only contract. confirm=false -> preview, confirm=true -> save (consumed value starts at 0)."""
    raw = await file.read()
    try: c = parse_contract_pdf(io.BytesIO(raw))
    except Exception as e: raise HTTPException(422, f"Could not extract automatically ({e}). Use manual entry.")
    c["source"] = "pdf"
    if confirm: _save_contract(c, who(x_user))
    return {**c, "start": str(c["start"]), "end": str(c["end"]), "saved": confirm}

@app.post("/api/contracts")
def contract_add(body: dict, x_user: str = Header(None)):
    try:
        c = {"contract_id": body["contract_id"].strip(), "supplier_id": body["supplier_id"].strip(), "start": pdate(body["start"]), "end": pdate(body["end"]),
             "cap": float(body["cap"]), "consumed": float(body.get("consumed", 0)), "lines": {k.strip(): float(v) for k, v in body["lines"].items()}, "source": "manual"}
    except Exception as e: raise HTTPException(400, f"bad contract data: {e}")
    _save_contract(c, who(x_user)); return {"ok": True}

# ------------------------------------------------------------- chat, audit
@app.post("/api/chat")
def chat_ep(body: dict, x_user: str = Header(None)):
    if not db.q("SELECT 1 FROM items LIMIT 1"): raise HTTPException(503, "Master data not loaded yet (Admin tab)")
    return chat.reply(body.get("session_id"), body.get("message", ""), who(x_user))

@app.post("/api/chat/stream")
async def chat_stream(body: dict, x_user: str = Header(None)):
    if not db.q("SELECT 1 FROM items LIMIT 1"):
        raise HTTPException(503, "Master data not loaded yet (Admin tab)")

    async def events():
        import asyncio
        result = await asyncio.to_thread(chat.reply, body.get("session_id"), body.get("message", ""), who(x_user))
        reply = str(result.get("reply", ""))
        chunk_size = 16
        for i in range(0, len(reply), chunk_size):
            yield f"data: {json.dumps({'type': 'delta', 'text': reply[i:i + chunk_size]})}\n\n"
            await asyncio.sleep(0.018)
        yield f"data: {json.dumps({'type': 'done', 'result': result})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/chat-pr-batch")
def chat_batch():
    b = db.q("SELECT id FROM batches WHERE source='chat'")
    return {"batch_id": b[0]["id"] if b else None}

@app.get("/api/audit")
def audit_log(limit: int = 200): return db.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

@app.get("/")
def root(): return {"service": "Corvo PR-to-PO API", "docs": "/docs", "health": "/api/health"}
