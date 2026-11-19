"use client";
import { useState, useEffect } from "react";
import PageHead from "../../components/PageHead";
import { api, toast } from "../../lib/api";
export default function Data() {
  const [S, setS] = useState(null);
  const [files, setFiles] = useState([]);
  const load = () =>
    api("/state")
      .then(setS)
      .catch((e) => toast(e.message, true));
  useEffect(() => {
    load();
  }, []);
  async function upload() {
    const f = new FormData();
    files.forEach((x) => f.append("files", x));
    try {
      toast("Loading…");
      await api("/admin/load-data", { method: "POST", body: f });
      toast("Master data loaded ✔");
      load();
    } catch (e) {
      toast(e.message, true);
    }
  }
  if (!S) return <PageHead title="Master data" sub="Loading…" />;
  return (
    <>
      <PageHead
        title="Master data"
        sub="Load the kit files once. Everything else works from this data."
      />
      <div className="card">
        <div className="stats">
          {[
            ["Items", S.items],
            ["Suppliers", S.suppliers],
            ["PO history", S.po_history],
            ["Contracts", S.contracts],
          ].map(([k, v]) => (
            <div className="stat" key={k}>
              <b>{v}</b>
              <span>{k}</span>
            </div>
          ))}
        </div>
        <div className="drop">
          <b>{S.data_loaded ? "Reload" : "Load"} master data</b>
          <p className="hint">
            Select all kit files together: item_master, supplier_master,
            po_history, plants, contract_register, contract_lines (CSV) and any
            RC-*.pdf
          </p>
          <input
            type="file"
            multiple
            onChange={(e) => setFiles([...e.target.files])}
          />
          <br />
          <br />
          <button className="btn p" disabled={!files.length} onClick={upload}>
            Load data
          </button>
        </div>
        <p className="hint" style={{ marginTop: 12 }}>
          Groq AI:{" "}
          {S.llm
            ? "connected"
            : "not configured - chat uses a basic parser, and policy documents cannot be read (JSON still works)."}
        </p>
      </div>
    </>
  );
}
