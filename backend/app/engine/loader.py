import csv, os, glob, re
from .util import pdate, num

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def find(dirpath, name):
    aliases = {
        "item_master.csv": ("item_master", "itemmaster", "itemdata"),
        "supplier_master.csv": ("supplier_master", "suppliermaster", "supplierdata"),
        "po_history.csv": ("po_history", "pohistory", "purchase_order_history"),
        "plants.csv": ("plants", "plant_master", "plantmaster"),
        "contract_register.csv": ("contract_register", "contractregister", "contracts", "contract_master"),
        "contract_lines.csv": ("contract_lines", "contractlines", "contract_line", "contractline", "contract_item_lines", "contract_items"),
    }
    wanted = aliases.get(name, (os.path.splitext(name)[0],))
    wanted = {re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_") for x in wanted}
    for path in glob.glob(os.path.join(dirpath, "**", "*"), recursive=True):
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != ".csv":
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        stem = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
        if stem in wanted:
            return path
    return None

def load_master(dirpath):
    def g(n):
        f = find(dirpath, n)
        if not f: raise FileNotFoundError(f"{n} not found in {dirpath}")
        return read_csv(f)
    items = [{**r, "standard_price": num(r["standard_price"])} for r in g("item_master.csv")]
    sup = [{"supplier_id": r["supplier_id"], "name": r["name"], "city": r["city"], "categories": [c.strip() for c in r["categories"].split(";")],
            "status": r["status"], "on_time_pct": num(r["on_time_pct"]), "quality_rating": num(r["quality_rating"])} for r in g("supplier_master.csv")]
    pos = [{"po_number": r["po_number"], "po_date": pdate(r["po_date"]), "supplier_id": r["supplier_id"], "item_code": r["item_code"],
            "quantity": num(r["quantity"]), "unit_price": num(r["unit_price"]), "plant": r["plant"],
            "delivered_on_time": r["delivered_on_time"] == "True"} for r in g("po_history.csv")]
    plants = [r["plant"] for r in g("plants.csv")]
    lines = {}
    contract_lines = find(dirpath, "contract_lines.csv")
    if contract_lines:
        for r in read_csv(contract_lines):
            contract_id = r.get("contract_id") or r.get("contract_no") or r.get("Contract ID")
            item_code = r.get("item_code") or r.get("item") or r.get("Item Code")
            rate = r.get("rate") or r.get("unit_price") or r.get("contract_rate") or r.get("Rate")
            if contract_id and item_code:
                lines.setdefault(contract_id.strip(), {})[item_code.strip()] = num(rate)
    contracts = [{"contract_id": r["contract_id"], "supplier_id": r["supplier_id"], "start": pdate(r["start_date"]), "end": pdate(r["end_date"]),
                  "cap": num(r["value_cap"]), "consumed": num(r["consumed_value"]), "source": "register",
                  "lines": lines.get(r["contract_id"], {})} for r in g("contract_register.csv")]
    return items, sup, pos, contracts, plants

def read_batch(path):
    return read_csv(path)

def load_pdf_contracts(dirpath, known_ids):
    """Contracts that exist only as signed PDFs (not in the register) start at zero consumed (policy 4.2/4.4)."""
    from ..contract_pdf import parse_contract_pdf
    out = []
    for p in sorted(glob.glob(os.path.join(dirpath, "**", "RC-*.pdf"), recursive=True)):
        cid = os.path.basename(p)[:-4]
        if cid in known_ids: continue
        out.append(parse_contract_pdf(p))
    return out
