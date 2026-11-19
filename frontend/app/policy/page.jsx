"use client";
import { useState, useEffect } from "react";
import PageHead from "../../components/PageHead";
import { api, J, fd, toast } from "../../lib/api";

const kind = (c) => (c.startsWith("NEW") ? "n" : c.startsWith("CHANGED") ? "c" : c.startsWith("REMOVED") ? "r" : "");

export default function Policy() {
  const [ps, setPs] = useState([]); const [draft, setDraft] = useState(null); const [view, setView] = useState(null);
  const [file, setFile] = useState(null); const [text, setText] = useState(""); const [json, setJson] = useState(""); const [showJson, setShowJson] = useState(false);
  const [eff, setEff] = useState("");
  const load = () => api("/policies").then(setPs).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
  const show = (r) => { setDraft(r); setEff(r.effective_date || ""); setTimeout(() => document.getElementById("draft")?.scrollIntoView({ behavior: "smooth" }), 50); };
  const make = guard(async (k) => {
    toast("Reading…");
    const body = k === "file" ? fd({ file }) : k === "text" ? fd({ text }) : fd({ policy_json: json });
    show(await api("/policies/draft", { method: "POST", body })); load();
  });
  const review = guard(async (id) => { const p = await api("/policies/" + id); show({ id, version: p.version, effective_date: p.effective_date, changes: p.changes, errors: [] }); });
  const activate = guard(async () => { await api(`/policies/${draft.id}/approve`, J("POST", { effective_date: eff })); toast("Policy activated ✔"); setDraft(null); load(); });
  const reject = guard(async () => { await api(`/policies/${draft.id}/reject`, { method: "POST" }); setDraft(null); load(); });
  const viewRules = guard(async (id) => setView(await api("/policies/" + id)));
  const step = !draft ? 1 : 2;
  return (
    <>
      <PageHead title="Procurement policy" sub="Rules and limits are stored as data. Change them here - no code change needed." />
      <div className="card"><h3>Update the policy</h3>
        <div className="steps">
          <div className={"step " + (step === 1 ? "on" : "done")}><i>1</i>Add change</div>
          <div className={"step " + (step === 2 ? "on" : "")}><i>2</i>Review what changes</div><div className="step"><i>3</i>Approve</div></div>
        <div className="row" style={{ alignItems: "stretch" }}>
          <div className="drop sp"><b>Upload amendment</b><p className="hint">PDF, text or JSON</p>
            <input type="file" accept=".pdf,.txt,.md,.json" onChange={(e) => setFile(e.target.files[0])} /><br /><br />
            <button className="btn s" disabled={!file} onClick={() => make("file")}>Read document</button></div>
          <div className="sp" style={{ minWidth: 280 }}><b>…or describe the change</b>
            <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. From 1 Dec 2026, spot-PO limit for Safety & PPE at CHK1 is ₹5,00,000" />
            <div className="row" style={{ marginTop: 8 }}><button className="btn p" disabled={!text} onClick={() => make("text")}>Draft change</button>
              <button className="btn s" onClick={() => setShowJson(!showJson)}>Paste JSON</button></div></div></div>
        {showJson && (<div style={{ marginTop: 10 }}><textarea rows={6} value={json} onChange={(e) => setJson(e.target.value)} placeholder='{"version":"5.1","effective_date":"2026-12-01",...}' />
          <button className="btn s" onClick={() => make("json")}>Draft from JSON</button></div>)}
        {draft && (
          <div id="draft" className="card" style={{ background: "#fafaff", margin: "14px 0 0" }}>
            <h3>Draft v{draft.version} - what will change</h3>
            {draft.errors.length > 0 ? (
              <div className="callout w"><b>Cannot activate - fix these:</b><ul>{draft.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
            ) : (<>
              {draft.changes.map((c, i) => <div key={i} className={"chg " + kind(c)}>{c}</div>)}
              <div className="row" style={{ marginTop: 12 }}><b>Effective from</b><input type="date" value={eff} onChange={(e) => setEff(e.target.value)} />
                <div className="sp" /><button className="btn d" onClick={reject}>Reject</button><button className="btn p" onClick={activate}>✔ Approve &amp; activate</button></div>
              <p className="hint" style={{ marginTop: 8 }}>Then go to Buyer workspace → “Reprocess with latest policy”.</p></>)}
          </div>)}
      </div>
      <div className="card"><h3>Versions</h3>
        <p className="hint">The version used for a requirement is the latest active one whose effective date is on or before the requirement date.</p>
        <table><thead><tr><th>Version</th><th>Effective from</th><th>Status</th><th>Source</th><th /></tr></thead><tbody>
          {ps.map((p) => (<tr key={p.id}><td><b>v{p.version}</b></td><td>{p.effective_date}</td>
            <td><span className={"pill " + (p.status === "active" ? "r-SPOT_PO" : p.status === "draft" ? "r-RFQ" : "")}>{p.status}</span></td>
            <td className="mut">{p.source}<br />{p.approved_by || p.created_by}</td>
            <td><button className="btn s" onClick={() => viewRules(p.id)}>View rules</button>{p.status === "draft" && <> <button className="btn p" onClick={() => review(p.id)}>Review</button></>}</td></tr>))}</tbody></table>
        {view && (<div><h3 style={{ marginTop: 18 }}>v{view.version} rules - checked top to bottom, first match wins</h3>
          {view.rules_text.map((t, i) => { const k = t.indexOf("]") + 1; return <div className="rule" key={i}><b>{t.slice(0, k)}</b>{t.slice(k)}</div>; })}
          <details><summary>Raw JSON</summary><pre>{JSON.stringify(view.body, null, 1)}</pre></details></div>)}
      </div>
    </>
  );
}
