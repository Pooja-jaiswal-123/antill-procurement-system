"use client";
import { useState, useEffect } from "react";
import PageHead from "../../components/PageHead";
import { api, inr, toast } from "../../lib/api";
export default function Preferred() {
  const [items, setItems] = useState([]); const [item, setItem] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10)); const [rows, setRows] = useState(null);
  useEffect(() => { api("/items").then((i) => { setItems(i); if (i[0]) setItem(i[0].item_code); }).catch((e) => toast(e.message, true)); }, []);
  useEffect(() => { if (item) api(`/preferred-suppliers/${item}?as_of=${date}`).then(setRows).catch((e) => toast(e.message, true)); }, [item, date]);
  return (
    <>
      <PageHead title="Preferred suppliers" sub="Ranked from purchase history (last 548 days) and contracts. Blocked and inactive suppliers never appear." />
      <div className="card">
        <div className="row">
          <select value={item} onChange={(e) => setItem(e.target.value)} style={{ minWidth: 300 }}>
            {items.map((i) => <option key={i.item_code} value={i.item_code}>{i.item_code} · {i.description}</option>)}</select>
          <span className="mut">as of</span><input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <div className="sp" /><a className="btn s" href={`/api/preferred-suppliers.csv?as_of=${date}`}>⬇ Export all items (CSV, top 3)</a>
        </div>
        <div style={{ marginTop: 14 }}>
          {rows && rows.length > 0 && (<table><thead><tr><th>Rank</th><th>Supplier</th><th>Reference price</th><th>Why</th></tr></thead><tbody>
            {rows.map((x) => (<tr key={x.supplier_id}><td><b>#{x.rank}</b></td><td>{x.supplier_id} {x.name}</td>
              <td>₹{inr(x.reference_price)}<div className="mut">{x.ref_source}</div></td><td className="mut">{x.why}</td></tr>))}</tbody></table>)}
          {rows && rows.length === 0 && <div className="empty">No active supplier has history for this item yet.</div>}
        </div>
      </div>
      <div className="card"><h3>How the ranking works</h3>
        <p className="hint">Score = 35% how often we bought + 25% how recently + 15% has held a contract + 15% on-time delivery + 10% quality. Weights are part of the policy.</p></div>
    </>
  );
}
