"""Chat intake. LLM (if configured) only EXTRACTS fields; the dialogue, item matching and PR creation are deterministic,
so the assistant can never invent an item or skip a required question."""
import re, json, uuid
from datetime import date, datetime, timedelta
from . import db, llm, services
from .engine import matcher

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
PLANT_WORDS = {"chakan": "CHK1", "chk1": "CHK1", "chk": "CHK1", "bhosari": "PUN1", "pune": "PUN1", "pun1": "PUN1", "pun": "PUN1"}
UOMS = r"(nos|pcs|pieces|pair|pairs|kg|kgs|ltr|litre|litres|liter|mtr|meter|meters|metre|metres|roll|rolls|box|boxes|cyl|job|set|sets|bkt|brl)"

SYSTEM = """Extract purchase-request fields from the user's latest message in a procurement chat. Return ONLY JSON:
{"item_text": string|null, "quantity": number|null, "uom": string|null, "plant": "PUN1"|"CHK1"|null, "need_by": "YYYY-MM-DD"|null,
 "urgency": "Normal"|"Emergency"|null, "estimated_unit_price": number|null, "answer": "yes"|"no"|null, "cancel": bool, "choice": integer|null}
Plant mapping: Chakan=CHK1, Bhosari or Pune=PUN1. Resolve relative dates using TODAY. urgency=Emergency only if the user says emergency/breakdown/line down/urgent-urgent; ordinary "urgent" is still Emergency only if they say it is an emergency, else null.
item_text is the product they want, copied from the user's words (do NOT correct or invent). Only fill fields the user actually stated in THIS message (or answered). "choice" = number if they pick an option from a list."""

def _resolve_date(text, today):
    t = text.lower()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m: return m.group(0), m.group(0)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s*(\d{4}))?", t)
    if m:
        y = int(m.group(3) or today.year); d = date(y, MONTHS[m.group(2)], int(m.group(1)))
        if not m.group(3) and d < today: d = date(y + 1, d.month, d.day)
        return d.isoformat(), m.group(0)
    if "tomorrow" in t: return (today + timedelta(days=1)).isoformat(), "tomorrow"
    m = re.search(r"in (\d+) days?", t)
    if m: return (today + timedelta(days=int(m.group(1)))).isoformat(), m.group(0)
    m = re.search(r"\b(next\s+|this\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = WEEKDAYS.index(m.group(2)); target = today + timedelta(days=(wd - today.weekday()) % 7 or 7)
        if (m.group(1) or "").strip() == "next" and target.isocalendar()[:2] == today.isocalendar()[:2]: target += timedelta(days=7)
        return target.isoformat(), m.group(0)
    return None, None

def fallback_extract(msg, today, state):
    t = msg.strip(); low = t.lower(); out = {"cancel": bool(re.search(r"\b(cancel|abort|start over|never ?mind)\b", low))}
    out["answer"] = "yes" if re.fullmatch(r"\s*(y|yes|yeah|yep|confirm|ok|okay|correct|sure|haan|ha)\W*", low) else ("no" if re.fullmatch(r"\s*(n|no|nope|nahi)\W*", low) else None)
    out["choice"] = int(low) if re.fullmatch(r"\s*[1-9]\s*", low) and state.get("options") else None
    rest = t
    plant = None
    for w, c in PLANT_WORDS.items():
        if re.search(rf"\b{w}\b", low): plant = c; rest = re.sub(rf"(?i)\b(for|at|to|in)?\s*\b{w}\b( plant)?", " ", rest); break
    out["plant"] = plant
    d, span = _resolve_date(t, today)
    out["need_by"] = d
    if span: rest = re.sub(rf"(?i)\b(by|before|on|need[- ]?by|needed by)?\s*{re.escape(span)}", " ", rest)
    out["urgency"] = "Emergency" if re.search(r"\bemergency|breakdown|line down\b", low) else ("Normal" if re.search(r"\bnormal|routine|not urgent\b", low) else None)
    rest = re.sub(r"(?i)\b(emergency|normal|routine)\b( urgency)?", " ", rest)
    m = re.search(rf"(?i)(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", t)
    out["estimated_unit_price"] = float(m.group(1).replace(",", "")) if m else None
    if m: rest = rest.replace(m.group(0), " ")
    qty = None
    m = re.search(rf"(?i)\b(?:qty|quantity)?\s*[:=]?\s*(\d[\d,]*(?:\.\d+)?)\s*{UOMS}?\b", rest) if not re.fullmatch(r"\s*[\d.,]+\s*", rest) else None
    if re.fullmatch(r"\s*\d[\d,]*(\.\d+)?\s*", t) and state.get("asking") == "quantity": out["quantity"] = float(t.replace(",", "")); out["item_text"] = None; out["uom"] = None; return out
    if re.fullmatch(r"\s*\d[\d,]*(\.\d+)?\s*", t) and state.get("asking") == "estimated_unit_price": out["estimated_unit_price"] = float(t.replace(",", "")); out["quantity"] = None; out["item_text"] = None; out["uom"] = None; return out
    if m and not state.get("asking") in ("plant", "need_by"):
        # skip numbers that are part of item specs (e.g. "6205", "m10") by taking the first number at start or after need/want/require
        lead = re.search(rf"(?i)\b(?:need|want|require|requires|order|buy|raise|pr for|get)\s+(?:about\s+)?(\d[\d,]*(?:\.\d+)?)\s*{UOMS}?\b", rest) or re.match(rf"\s*(\d[\d,]*(?:\.\d+)?)\s*{UOMS}?\b", rest)
        if lead: qty = float(lead.group(1).replace(",", "")); rest = rest.replace(lead.group(0), " ", 1)
    out["quantity"] = qty; out["uom"] = None
    rest = re.sub(r"(?i)\b(i|we)?\s*(need|want|require|please|pls|raise|a pr for|pr for|order|buy|get)\b", " ", rest)
    rest = re.sub(r"(?i)\b(by|for|at)\b\s*$", " ", rest)
    item = re.sub(r"\s+", " ", rest).strip(" ,.-:;")
    out["item_text"] = item if len(item) >= 3 and not state.get("asking") in ("quantity", "plant", "need_by", "urgency", "estimated_unit_price") else (item if len(item) >= 3 and state.get("asking") == "item" else None)
    return out

def extract(msg, today, state):
    if llm.available():
        try:
            j = llm.complete_json(SYSTEM, f"TODAY: {today.isoformat()} ({today.strftime('%A')})\nCURRENT DRAFT: {json.dumps(state['draft'])}\nWE ARE ASKING FOR: {state.get('asking')}\nOPTIONS SHOWN: {state.get('options')}\nUSER MESSAGE: {msg}")
            j.setdefault("cancel", False); return j
        except Exception:
            pass
    return fallback_extract(msg, today, state)

VAGUE = {"some", "any", "item", "items", "stuff", "material", "materials", "spare", "spares", "parts", "part"}
def _keyword_cands(text, ref):
    toks = [t for t in matcher.norm(text) if len(t) >= 4 and not t.isdigit() and t not in VAGUE]
    toks = [t[:-1] if t.endswith("s") else t for t in toks]
    hits = [it for it in ref["items"].values() if any(t in " ".join(matcher.norm(it["description"])) for t in toks)] if toks else []
    return [{"item_code": i["item_code"], "description": i["description"], "score": 0.0} for i in hits[:5]]

def new_state(): return {"draft": {}, "stage": "collect", "asking": None, "options": None, "new_item": False}

def _load(sid):
    r = db.q("SELECT state FROM chat_sessions WHERE id=?", (sid,))
    return json.loads(r[0]["state"]) if r else new_state()

def _save(sid, st):
    if db.POSTGRES:
        db.x("INSERT INTO chat_sessions(id,state,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=EXCLUDED.state, updated_at=EXCLUDED.updated_at", (sid, json.dumps(st), db.now()))
    else:
        db.x("INSERT INTO chat_sessions(id,state,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at", (sid, json.dumps(st), db.now()))

QUESTIONS = {"quantity": "How many do you need?", "plant": "Which plant is it for - Pune/Bhosari (PUN1) or Chakan (CHK1)?",
             "need_by": "By which date do you need it? (e.g. 27 Nov or next Friday)", "urgency": "Is this Normal or an Emergency (line-down / breakdown)?",
             "estimated_unit_price": "This item is not in the item master, so it will go to sourcing. What is your estimated price per unit (INR)?"}

def _summary(d):
    item = f"{d['item_code']} - {d['item_desc']}" if d.get("item_code") else f"NEW ITEM: {d['item_text']}"
    return (f"**{d['quantity']:g} x {item}**\nPlant: {d['plant']} | Need by: {d['need_by']} | Urgency: {d['urgency']}"
            + (f" | Est. unit price: ₹{d['estimated_unit_price']:,.2f}" if d.get("estimated_unit_price") else ""))

def reply(sid, msg, actor="requester"):
    sid = sid or uuid.uuid4().hex[:10]
    st = _load(sid); today = date.today(); d = st["draft"]
    ref = services.load_ref()
    e = extract(msg, today, st)
    if e.get("cancel"):
        _save(sid, new_state()); return {"session_id": sid, "reply": "Okay, cancelled. Tell me what you need whenever you are ready.", "draft": {}, "chips": []}

    # confirmation stage
    if st["stage"] == "confirm":
        if e.get("answer") == "yes":
            pr = create_pr(d, actor)
            _save(sid, new_state())
            return {"session_id": sid, "reply": f"Done. PR **{pr}** is created. Procurement will see it in the Buyer workspace after the next engine run.", "draft": {}, "chips": ["Raise another PR"], "pr_no": pr, "next": "workspace"}
        if e.get("answer") == "no":
            st["stage"] = "collect"; st["asking"] = None; _save(sid, st)
            return {"session_id": sid, "reply": "No problem - what should I change? (item, quantity, plant, date or urgency)", "draft": d, "chips": []}
        st["stage"] = "collect"

    # option pick (ambiguous item)
    if st.get("options") and e.get("choice"):
        try:
            pick = st["options"][int(e["choice"]) - 1]
            d["item_code"], d["item_desc"] = pick["item_code"], pick["description"]; st["options"] = None; st["new_item"] = False
        except Exception: pass
    elif st.get("options") and re.search(r"(?i)\b(none|new|not (in )?(the )?list|other)\b", msg):
        st["new_item"] = True; st["options"] = None; d["item_code"] = None
    m = re.search(r"(?i)\bITM-\d{4}\b", msg)
    if m and m.group(0).upper() in ref["items"]:
        it = ref["items"][m.group(0).upper()]; d["item_code"], d["item_desc"] = it["item_code"], it["description"]

    # a later message that clearly names a master item overrides a vague / new-item guess
    if (st.get("new_item") or st.get("options")) and not e.get("choice") and len(msg.split()) >= 2:
        code, conf, _ = matcher.match(msg, ref["items"])
        if code: d["item_code"], d["item_desc"], d["item_text"] = code, ref["items"][code]["description"], msg; st["new_item"] = False; st["options"] = None; st["asking"] = None; e["item_text"] = None

    # merge slots
    if e.get("item_text") and (not d.get("item_code") or st.get("asking") == "item") and not st.get("options"):
        if e["item_text"] != d.get("item_text"): d["item_code"] = None; d["item_desc"] = None; st["new_item"] = False
        d["item_text"] = e["item_text"]
    for k in ("quantity", "need_by", "urgency", "estimated_unit_price"):
        if e.get(k) not in (None, ""): d[k] = e[k]
    if e.get("plant"):
        if e["plant"] in ref["plants"]: d["plant"] = e["plant"]
    if e.get("uom"): d["uom"] = e["uom"]
    if d.get("quantity") is not None and float(d["quantity"]) <= 0:
        d.pop("quantity"); _save(sid, st); return {"session_id": sid, "reply": "Quantity must be more than zero. How many do you need?", "draft": d, "chips": []}
    if d.get("need_by") and d["need_by"] < today.isoformat():
        d.pop("need_by"); st["asking"] = "need_by"; _save(sid, st)
        return {"session_id": sid, "reply": "That date is already in the past. Which date do you need it by?", "draft": d, "chips": []}

    # fallback parser: a stray number in the item text that lowers the match is the quantity ("brg 6308 zz 50")
    if d.get("item_text") and d.get("quantity") in (None, "") and not d.get("item_code"):
        words = d["item_text"].split()
        best = matcher.candidates(d["item_text"], ref["items"], 1)
        base = best[0]["score"] if best else 0
        for w in [w for w in words if re.fullmatch(r"\d{1,6}", w)]:
            alt = " ".join(x for x in words if x != w); c2 = matcher.candidates(alt, ref["items"], 1)
            if c2 and c2[0]["score"] > base + 0.03 and w not in ref["items"][c2[0]["item_code"]]["description"]:
                d["quantity"] = float(w); d["item_text"] = alt; base = c2[0]["score"]

    # item resolution - only from the item master
    if d.get("item_text") and not d.get("item_code") and not st.get("new_item") and not st.get("options"):
        code, conf, cands = matcher.match(d["item_text"], ref["items"])
        if code: d["item_code"], d["item_desc"] = code, ref["items"][code]["description"]
        elif (cands and cands[0]["score"] >= 0.45) or _keyword_cands(d["item_text"], ref):
            cands = [c for c in cands if c["score"] >= 0.3][:4] if cands and cands[0]["score"] >= 0.45 else _keyword_cands(d["item_text"], ref)
            st["options"] = cands[:5]; st["asking"] = "item"; _save(sid, st)
            lines = "\n".join(f"{i+1}. {c['item_code']} - {c['description']}" for i, c in enumerate(st["options"]))
            return {"session_id": sid, "reply": f"I could not match \"{d['item_text']}\" with certainty. Did you mean one of these?\n{lines}\nReply with a number, or say **none** if it is a new item.",
                    "draft": d, "chips": [str(i + 1) for i in range(len(st["options"]))] + ["none - new item"]}
        else:
            st["new_item"] = True
    if not d.get("item_text") and not d.get("item_code"):
        st["asking"] = "item"; _save(sid, st)
        return {"session_id": sid, "reply": "Hi! What do you need? e.g. \"200 nitrile gloves for Chakan by next Friday\".", "draft": d, "chips": []}

    need = [k for k in ("quantity", "plant", "need_by", "urgency") if d.get(k) in (None, "")]
    if st["new_item"] and d.get("estimated_unit_price") in (None, ""): need.append("estimated_unit_price")
    if need:
        k = need[0]; st["asking"] = k; _save(sid, st)
        pre = ""
        if st["new_item"] and not st.get("told_new"): pre = f"\"{d['item_text']}\" is not in the item master, so I will raise it as a **new item** (it goes to sourcing). "; st["told_new"] = True; _save(sid, st)
        elif d.get("item_code") and not st.get("said_match"): pre = f"Matched to **{d['item_code']} - {d['item_desc']}**. "; st["said_match"] = True; _save(sid, st)
        chips = {"plant": ["PUN1", "CHK1"], "urgency": ["Normal", "Emergency"]}.get(k, [])
        return {"session_id": sid, "reply": pre + QUESTIONS[k], "draft": d, "chips": chips}

    st["stage"] = "confirm"; st["asking"] = None; _save(sid, st)
    return {"session_id": sid, "reply": _summary(d) + "\n\nShall I create this PR?", "draft": d, "chips": ["Yes", "No, change something"]}

def create_pr(d, actor):
    b = db.q("SELECT id FROM batches WHERE source='chat'")
    bid = b[0]["id"] if b else db.x("INSERT INTO batches(name,source,created_by,created_at) VALUES(?,?,?,?)", ("Chat PRs", "chat", "system", db.now()))
    n = db.q("SELECT COUNT(*) c FROM pr_lines")[0]["c"] + 1
    pr_no = f"PR-CH-{n:05d}"
    ref = services.load_ref()
    uom = ref["items"][d["item_code"]]["uom"] if d.get("item_code") else d.get("uom", "NOS")
    db.x("INSERT INTO pr_lines(batch_id,pr_no,pr_line,created_at,requester,department,plant,item_code,description,quantity,uom,estimated_unit_price,need_by_date,urgency) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (bid, pr_no, "1", datetime.now().strftime("%Y-%m-%d %H:%M"), actor, "", d["plant"], d.get("item_code") or "", d.get("item_desc") or d["item_text"],
          str(d["quantity"]), uom, str(d.get("estimated_unit_price") or ""), d["need_by"], d["urgency"]))
    db.audit(actor, "create_pr_chat", f"pr:{pr_no}", d)
    return pr_no
