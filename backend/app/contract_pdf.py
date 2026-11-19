"""Extract a rate contract from its signed PDF (template-based regex; LLM fallback lives in llm.py)."""
import re
from datetime import datetime
from pypdf import PdfReader

def pdf_text(path_or_file):
    return "\n".join((p.extract_text() or "") for p in PdfReader(path_or_file).pages)

def _d(s): return datetime.strptime(s, "%Y-%m-%d").date()

def parse_contract_text(t):
    t1 = re.sub(r"\s+", " ", t)
    cid = re.search(r"Contract No\.?\s*(RC-\d{4}-\d+)", t1)
    sup = re.search(r"\(Supplier ID\s*(S\d+)\)", t1)
    term = re.search(r"valid from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", t1)
    cap = re.search(r"shall not exceed INR\s*([\d,]+(?:\.\d+)?)", t1)
    if not (cid and sup and term and cap):
        raise ValueError("Could not find contract no / supplier / term / ceiling in PDF text")
    lines = {}
    sched = t.split("Schedule A")[-1]
    for m in re.finditer(r"^\s*\d+\s+(ITM-\d+)\s+(.+?)\s+([A-Z]{2,4})\s+([\d,]+\.\d{2})\s*$", sched, re.M):
        lines[m.group(1)] = float(m.group(4).replace(",", ""))
    if not lines: raise ValueError("No item lines found in Schedule A")
    return {"contract_id": cid.group(1), "supplier_id": sup.group(1), "start": _d(term.group(1)), "end": _d(term.group(2)),
            "cap": float(cap.group(1).replace(",", "")), "consumed": 0.0, "source": "pdf", "lines": lines}

def parse_contract_pdf(path_or_file):
    return parse_contract_text(pdf_text(path_or_file))
