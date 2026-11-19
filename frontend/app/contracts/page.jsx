"use client";
import { useState, useEffect } from "react";
import PageHead from "../../components/PageHead";
import { api, J, fd, inr, toast } from "../../lib/api";

export default function Contracts() {
  const [cs, setCs] = useState([]); const [file, setFile] = useState(null); const [prev, setPrev] = useState(null);
  const [manual, setManual] = useState(false);
  const [m, setM] = useState({ contract_id: "", supplier_id: "", start: "", end: "", cap: "", lines: "" });
  const load = () => api("/contracts").then(setCs).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  const guard = (fn) => async () => { try { await fn(); } catch (e) { toast(e.message, true); } };
  const extract = guard(async () => {
    if (!file) return toast("Choose a PDF first", true);
    setPrev(await api("/contracts/extract", { method: "POST", body: fd({ file }) }));
  });
  const save = guard(async () => { await api("/contracts/extract?confirm=true", { method: "POST", body: fd({ file }) }); toast("Contract saved"); setPrev(null); load(); });
  const saveManual = guard(async () => {
    const lines = {}; m.lines.split("\n").filter((x) => x.trim()).forEach((x) => { const [a, b] = x.split(","); lines[a.trim()] = b.trim(); });
    await api("/contracts", J("POST", { ...m, lines })); toast("Contract saved"); load();
  });
  const set = (k) => (e) => setM({ ...m, [k]: e.target.value });
  return (
    <>
      <PageHead title="Rate contracts" sub="Contracts signed after the register update exist only as PDFs - add them here so the engine can use them." />
      <div className="card"><h3>Add a contract</h3>
        <div className="row"><input type="file" accept=".pdf" onChange={(e) => setFile(e.target.files[0])} />
          <button className="btn p" onClick={extract}>Extract from PDF</button><button className="btn s" onClick={() => setManual(!manual)}>Enter manually</button></div>
        {prev && (<div className="callout" style={{ marginTop: 12 }}><b>Extracted - please check before saving</b>
          <div className="kv" style={{ marginTop: 8 }}><div>Contract</div><div>{prev.contract_id}</div><div>Supplier</div><div>{prev.supplier_id}</div>
            <div>Valid</div><div>{prev.start} → {prev.end}</div><div>Ceiling</div><div>₹{inr(prev.cap)} (used starts at 0)</div>
            <div>Items</div><div>{Object.entries(prev.lines).map(([k, v]) => <div key={k}>{k} @ ₹{inr(v)}</div>)}</div></div><br />
          <button className="btn p" onClick={save}>✔ Save contract</button></div>)}
        {manual && (<div style={{ marginTop: 12 }}>
          <div className="row"><input placeholder="Contract no. RC-2026-040" value={m.contract_id} onChange={set("contract_id")} />
            <input placeholder="Supplier S0xx" style={{ width: 120 }} value={m.supplier_id} onChange={set("supplier_id")} />
            <input type="date" value={m.start} onChange={set("start")} /><input type="date" value={m.end} onChange={set("end")} />
            <input placeholder="Ceiling ₹" style={{ width: 130 }} value={m.cap} onChange={set("cap")} /></div>
          <textarea rows={3} style={{ marginTop: 8 }} placeholder="One item per line:  ITM-1001, 6340.39" value={m.lines} onChange={set("lines")} /><br />
          <button className="btn p" onClick={saveManual}>Save contract</button></div>)}
      </div>
      <div className="card"><div className="tw"><table><thead><tr><th>Contract</th><th>Supplier</th><th>Valid</th><th>Ceiling (₹)</th><th>Used (₹)</th><th>Items &amp; rates</th></tr></thead><tbody>
        {cs.map((c) => { const pct = Math.min(100, Math.round((100 * c.consumed_value) / c.value_cap)); return (
          <tr key={c.contract_id}><td><b>{c.contract_id}</b><div className="mut">{c.source}</div></td>
            <td>{c.supplier_id} {c.supplier_name}{c.supplier_status !== "Active" && <span className="tag e">{c.supplier_status}</span>}</td>
            <td>{c.start_date}<br />→ {c.end_date}</td><td>{inr(c.value_cap)}</td>
            <td>{inr(c.consumed_value)}<div style={{ height: 6, background: "#eceff7", borderRadius: 9, marginTop: 4 }}>
              <div style={{ height: 6, width: pct + "%", background: pct > 90 ? "var(--bad)" : "var(--pri)", borderRadius: 9 }} /></div></td>
            <td>{Object.entries(c.lines).map(([k, v]) => <div key={k}>{k} @ ₹{inr(v)}</div>)}</td></tr>); })}</tbody></table></div></div>
    </>
  );
}
