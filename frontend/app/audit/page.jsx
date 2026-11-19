"use client";
import { useState, useEffect } from "react";
import PageHead from "../../components/PageHead";
import { api, toast } from "../../lib/api";
export default function Audit() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api("/audit").then(setRows).catch((e) => toast(e.message, true)); }, []);
  return (
    <>
      <PageHead title="Audit log" sub="Every action, with who and when." />
      <div className="card tw"><table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th>Details</th></tr></thead><tbody>
        {rows.map((r) => (<tr key={r.id}><td>{r.at}</td><td>{r.actor}</td><td><span className="pill">{r.action}</span></td><td>{r.entity}</td>
          <td className="mut" style={{ maxWidth: 460, wordBreak: "break-word" }}>{r.detail}</td></tr>))}</tbody></table></div>
    </>
  );
}
