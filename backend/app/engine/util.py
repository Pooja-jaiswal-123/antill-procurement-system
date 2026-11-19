from datetime import datetime, date

def pdate(s):
    if isinstance(s, datetime): return s.date()
    if isinstance(s, date): return s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()

def pdt(s):
    if isinstance(s, datetime): return s
    s = str(s).strip().replace("T", " ")
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return datetime.strptime(s, f)
        except ValueError: pass
    raise ValueError(f"bad datetime {s}")

def num(x):
    try:
        if x is None or str(x).strip() == "": return None
        return float(str(x).replace(",", ""))
    except ValueError:
        return None

OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "lt": lambda a, b: a is not None and a < b, "lte": lambda a, b: a is not None and a <= b,
    "gt": lambda a, b: a is not None and a > b, "gte": lambda a, b: a is not None and a >= b,
    "in": lambda a, b: a in b, "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in (a or ""),
}

def eval_cond(c, facts):
    if "all" in c: return all(eval_cond(x, facts) for x in c["all"])
    if "any" in c: return any(eval_cond(x, facts) for x in c["any"])
    if "not" in c: return not eval_cond(c["not"], facts)
    return OPS[c["op"]](facts.get(c["field"]), c["value"])

def describe_cond(c):
    if "all" in c: return " AND ".join(describe_cond(x) for x in c["all"]) or "always"
    if "any" in c: return "(" + " OR ".join(describe_cond(x) for x in c["any"]) + ")"
    if "not" in c: return "NOT " + describe_cond(c["not"])
    sym = {"eq": "=", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "in": "in", "not_in": "not in", "contains": "contains"}[c["op"]]
    v = c["value"]
    if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000: v = f"{v:,.0f}"
    return f"{c['field']} {sym} {v}"
