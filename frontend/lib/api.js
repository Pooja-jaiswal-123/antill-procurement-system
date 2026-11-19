export async function api(path, opt = {}) {
  const who = (typeof window !== "undefined" && localStorage.getItem("who")) || "buyer";
  opt.headers = { ...(opt.headers || {}), "X-User": who };
  const r = await fetch("/api" + path, opt);
  if (!r.ok) {
    let m = r.statusText;
    try { m = (await r.json()).detail || m; } catch (e) {}
    throw new Error(typeof m === "string" ? m : JSON.stringify(m));
  }
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r.text();
}
export const J = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const fd = (o) => { const f = new FormData(); for (const k in o) if (o[k] != null) f.append(k, o[k]); return f; };
export const inr = (v) => (v === "" || v == null ? "" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
export function toast(m, bad) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : ""); t.textContent = m; document.body.append(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3200);
}
export const HELP = {
  CONTRACT_PO: "Buy from the rate-contract supplier at the contract rate.",
  SPOT_PO: "Order directly from the best known supplier (small value, bought before).",
  EMERGENCY_PO: "Emergency order straight to the best known supplier, no quotes.",
  RFQ: "Get quotes first - send a Request for Quotation to 3 suppliers.",
  RFP: "High value - run a formal Request for Proposal with 5 suppliers.",
  CAPEX_SOURCING: "Capital item - needs capex approval; get quotes from 5 suppliers.",
  NEW_ITEM_SOURCING: "Item not in master - buyer must find suppliers.",
  NOT_PROCESSED: "Data problem - ask the requester to correct the PR.",
};
