"use client";
import { useState, useEffect, useCallback } from "react";
import PageHead from "../../components/PageHead";
import { api, J, fd, inr, toast, HELP } from "../../lib/api";

const DIRECT = ["CONTRACT_PO", "SPOT_PO", "EMERGENCY_PO"];
const SOURCING = ["RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING"];
const label = (s) => s.replace(/_/g, " ");

export default function Workspace() {
  const [runs, setRuns] = useState(null);
  const [run, setRun] = useState(null);
  const [filter, setFilter] = useState(null);
  const [sel, setSel] = useState(null);

  const select = useCallback(async (id) => { setRun(await api("/runs/" + id)); setFilter(null); }, []);
  const load = useCallback(async (pick) => {
    const rs = await api("/runs"); setRuns(rs);
    if (pick || rs.length) await select(pick || rs[0].id);
  }, [select]);
  useEffect(() => { load().catch((e) => toast(e.message, true)); }, [load]);

  const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
  const upload = guard(async (e) => {
    const f = e.target.files[0]; if (!f) return;
    toast("Processing…");
    const r = await api("/batches", { method: "POST", body: fd({ file: f }) });
    await load(r.run_id); toast("Done - " + Object.values(r.summary).reduce((a, b) => a + b, 0) + " lines processed");
  });
  const processChat = guard(async () => {
    const b = await api("/chat-pr-batch");
    if (!b.batch_id) return toast("No chat requests yet - raise one in Chat first.", true);
    const r = await api(`/batches/${b.batch_id}/reprocess`, { method: "POST" }); await load(r.run_id);
  });
  const reprocess = guard(async () => {
    const r = await api(`/batches/${run.batch_id}/reprocess`, { method: "POST" });
    await load(r.run_id); toast("Reprocessed with the latest active policy");
  });
  const approve = guard(async (g) => { const r = await api(`/runs/${run.id}/requirements/${g}/approve`, { method: "POST" }); toast("Created " + r.created); await select(run.id); });
  const override = guard(async (g, body) => { await api(`/runs/${run.id}/requirements/${g}/override`, J("POST", body)); toast("Override saved"); await select(run.id); });

  const uploadBtn = (
    <label className="btn s">⬆ Upload PR batch (CSV)<input type="file" accept=".csv" className="hide" onChange={upload} /></label>
  );
  if (runs === null) return <PageHead title="Buyer workspace" sub="Loading…" />;

  const R = run;
  const sum = R?.summary || {};
  const tot = (ks) => ks.reduce((a, k) => a + (sum[k] || 0), 0);
  const open = R ? R.requirements.filter((r) => r.route !== "NOT_PROCESSED" && !R.status[r.group_id]).length : 0;
  const reqs = R ? R.requirements.filter((r) => r.route !== "NOT_PROCESSED" && (!filter || r.route === filter)) : [];
  const np = R ? R.rows.filter((r) => r.route === "NOT_PROCESSED") : [];
  const cur = R && sel ? R.requirements.find((r) => r.group_id === sel) : null;

  return (
    <>
      <PageHead title="Buyer workspace" sub="Review what the policy decided for every purchase requirement, then approve or override.">
        {uploadBtn}<button className="btn s" onClick={processChat}>Process chat requests</button>
      </PageHead>
      {!R ? (
        <div className="card empty"><div className="big">📥</div><h3>No decisions yet</h3>
          <p>Upload a PR batch CSV to see decisions, or raise a request in Chat and click “Process chat requests”.</p></div>
      ) : (
        <>
          <div className="card row">
            <span className="mut">Showing run</span>
            <select value={R.id} onChange={(e) => select(e.target.value)}>
              {runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.created_at} · policy v{JSON.parse(r.policy_versions).join("/")}</option>)}
            </select>
            <div className="sp" />
            <button className="btn s" onClick={reprocess}>↻ Reprocess with latest policy</button>
            <a className="btn s" href={`/api/runs/${R.id}/export.csv`}>⬇ Export CSV</a>
          </div>
          <div className="stats">
            <div className="stat act"><b>{open}</b><span>Waiting for your action</span></div>
            <div className="stat"><b>{R.requirements.length}</b><span>Requirements (from {R.rows.length} PR lines)</span></div>
            <div className="stat"><b>{tot(DIRECT)}</b><span>Direct POs</span></div>
            <div className="stat"><b>{tot(SOURCING)}</b><span>Sourcing requests</span></div>
            <div className="stat"><b>{sum.NOT_PROCESSED || 0}</b><span>Need correction</span></div>
          </div>
          <div className="card">
            <div className="filters">
              <button className={filter ? "" : "on"} onClick={() => setFilter(null)}>All</button>
              {Object.keys(sum).map((k) => <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{label(k)} · {sum[k]}</button>)}
            </div>
            <p className="hint">Click a row to see why the policy decided this, and to approve it.</p>
            <div className="tw"><table>
              <thead><tr><th>Req</th><th>Item</th><th>Plant</th><th>Value (₹)</th><th>Decision</th><th>Supplier / suggested</th><th>Status</th></tr></thead>
              <tbody>{reqs.map((r) => {
                const st = R.status[r.group_id];
                return (
                  <tr key={r.group_id} className="click" onClick={() => setSel(r.group_id)}>
                    <td><b>{r.group_id.replace("REQ-", "#")}</b>{r.emergency && <span className="tag e">EMERGENCY</span>}
                      <div className="mut">{r.lines.length > 1 ? r.lines.length + " PR lines clubbed" : r.lines[0]}</div></td>
                    <td>{r.item_code}</td><td>{r.plant}</td><td>{inr(r.value)}</td>
                    <td><span className={"pill r-" + r.route}>{label(r.route)}</span></td>
                    <td>{r.supplier ? <><b>{r.supplier}</b> @ ₹{inr(r.price)}<span className="tag">{r.po_id}</span></> : r.suggested.join(", ") || "—"}</td>
                    <td>{st ? <span className="pill r-SPOT_PO">{st.kind === "approve" ? "✔ approved" : "✎ overridden"}</span> : <span className="pill">open</span>}</td>
                  </tr>);
              })}</tbody></table></div>
          </div>
          {np.length > 0 && (!filter || filter === "NOT_PROCESSED") && (
            <div className="card"><h3>⚠ Needs correction ({np.length})</h3><p className="hint">These PR lines were not processed. Ask the requester to fix them.</p>
              {np.map((r) => <div key={r.pr_no + r.pr_line} className="callout w"><b>{r.pr_no} / {r.pr_line}</b> - {r.reason.replace("NOT_PROCESSED: ", "")}</div>)}</div>
          )}
        </>
      )}
      {cur && <Drawer r={cur} st={R.status[cur.group_id]} onClose={() => setSel(null)} onApprove={approve} onOverride={override} />}
    </>
  );
}

function Drawer({ r, st, onClose, onApprove, onOverride }) {
  const [comment, setComment] = useState(""); const [route, setRoute] = useState(""); const [sup, setSup] = useState("");
  return (
    <>
      <div className="ov" onClick={onClose} />
      <div className="drawer">
        <div className="dh row"><div><h2 style={{ margin: 0 }}>{r.item_code} · {r.plant}</h2>
          <span className={"pill r-" + r.route}>{label(r.route)}</span><span className="tag">policy v{r.policy_version} · clause {r.clause}</span></div>
          <div className="sp" /><button className="btn s" onClick={onClose}>✕ Close</button></div>
        <div className="db">
          <div className="callout"><b>What happens:</b> {HELP[r.route]}<br /><span className="mut">{r.reason}</span></div>
          <div className="box"><h4>Summary</h4><div className="kv">
            <div>Value</div><div><b>₹{inr(r.value)}</b> <span className="mut">({r.value_src})</span></div>
            <div>Quantity</div><div>{r.qty} · {r.lines.length} PR line(s): {r.lines.join(", ")}</div>
            <div>Requirement date</div><div>{r.date}{r.emergency && <span className="tag e">Emergency</span>}</div>
            <div>{r.supplier ? "Supplier" : "Suggested"}</div>
            <div>{r.supplier ? <><b>{r.supplier}</b> at ₹{inr(r.price)} · {r.po_id}</> : r.suggested.join(", ") || "none - buyer finds suppliers"}</div></div></div>
          <div className="box"><h4>Rules checked, in order (first match wins)</h4>
            {r.trace.map((t, i) => <div key={i} className={"tr " + (t.includes("MATCH") ? "m" : "")}>{t}</div>)}</div>
          {r.contracts.length > 0 && <div className="box"><h4>Contracts considered</h4>
            {r.contracts.map((c) => (<div className="row" style={{ padding: "4px 0" }} key={c.contract_id}><b>{c.contract_id}</b><span>{c.supplier_id}</span><span>₹{inr(c.rate)}</span>
              <span className="mut">ceiling left ₹{inr(c.ceiling_left)}</span><span className={"pill " + (c.fits ? "r-SPOT_PO" : "r-NOT_PROCESSED")}>{c.fits ? "has room" : "over ceiling"}</span></div>))}</div>}
          {r.preferred.length > 0 && <div className="box"><h4>Preferred suppliers - why ranked</h4>
            {r.preferred.map((p) => (<div key={p.supplier_id} style={{ padding: "6px 0", borderBottom: "1px dashed var(--line)" }}>
              <b>#{p.rank} {p.supplier_id}</b> {p.name} · ₹{inr(p.reference_price)}
              <div className="mut" style={{ fontSize: 12.5 }}>{p.why} · {p.ref_source}</div></div>))}</div>}
          {st ? (
            <div className="callout ok"><b>{st.kind === "approve" ? "✔ Approved" : "✎ Overridden"}</b> by {st.actor} on {st.at}
              {st.comment && <><br />Reason: {st.comment}</>}{st.payload.doc && <><br />Created: <b>{st.payload.doc}</b></>}</div>
          ) : (
            <div className="box"><h4>Your action</h4>
              <button className="btn p" onClick={() => onApprove(r.group_id)}>✔ Approve - create {r.decision === "PO" ? "PO " + r.po_id : label(r.route)}</button>
              <details><summary>Disagree? Override with a reason</summary>
                <div style={{ marginTop: 10 }}>
                  <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why are you overriding? (required)" />
                  <div className="row" style={{ marginTop: 8 }}>
                    <select value={route} onChange={(e) => setRoute(e.target.value)}><option value="">Keep route</option>
                      {["CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO", "RFQ", "RFP", "CAPEX_SOURCING"].map((x) => <option key={x}>{x}</option>)}</select>
                    <input value={sup} onChange={(e) => setSup(e.target.value)} placeholder="Supplier ID (optional)" style={{ width: 170 }} />
                    <button className="btn d" onClick={() => onOverride(r.group_id, { comment, route, supplier_id: sup })}>Override</button>
                  </div></div></details></div>
          )}
        </div>
      </div>
    </>
  );
}
