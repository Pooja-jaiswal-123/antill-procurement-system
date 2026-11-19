"use client";
import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import PageHead from "../../components/PageHead";
import { api, J, inr } from "../../lib/api";

const EXAMPLES = [
  "200 nitrile gloves for Chakan by next Friday",
  "brg 6308 zz for Pune, 50 nos, tomorrow",
  "need some bearings",
];
const bold = (t) =>
  t.split(/\*\*(.+?)\*\*/g).map((s, i) => (i % 2 ? <b key={i}>{s}</b> : s));

export default function Chat() {
  const [msgs, setMsgs] = useState([
    { from: "bot", t: "Hi! 👋 What do you need today? Try one of these:" },
  ]);
  const [chips, setChips] = useState(EXAMPLES);
  const [draft, setDraft] = useState({});
  const [sid, setSid] = useState(null);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState(false);
  const log = useRef();
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [msgs, typing]);

  async function send(m) {
    m = (m ?? text).trim();
    if (!m || busy) return;
    setText("");
    setChips([]);
    setDone(false);
    setBusy(true);
    setTyping(true);
    setMsgs((x) => [...x, { from: "me", t: m }]);

    try {
      const who = localStorage.getItem("who") || "buyer";
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User": who },
        body: JSON.stringify({ session_id: sid, message: m }),
      });
      if (!response.ok) throw new Error(await response.text());
      if (!response.body)
        throw new Error("Streaming is not supported by this browser");

      setTyping(false);
      setMsgs((x) => [...x, { from: "bot", t: "", streaming: true }]);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          if (!frame.startsWith("data: ")) continue;
          const event = JSON.parse(frame.slice(6));
          if (event.type === "delta") {
            setMsgs((x) =>
              x.map((msg, i) =>
                i === x.length - 1 ? { ...msg, t: msg.t + event.text } : msg,
              ),
            );
          } else if (event.type === "done") {
            const r = event.result;
            setSid(r.pr_no ? null : r.session_id);
            setDraft(r.pr_no ? {} : r.draft || {});
            setMsgs((x) =>
              x.map((msg, i) =>
                i === x.length - 1 ? { ...msg, streaming: false } : msg,
              ),
            );
            setChips(r.chips || []);
            if (r.pr_no) setDone(true);
          }
        }
      }
    } catch (e) {
      setTyping(false);
      setMsgs((x) => [...x, { from: "bot", t: "Sorry - " + e.message }]);
    }
    setBusy(false);
  }

  const d = draft;
  const rows = [
    [
      "Item",
      d.item_code
        ? `${d.item_code} · ${d.item_desc}`
        : d.item_text
          ? `NEW: ${d.item_text}`
          : "",
    ],
    ["Quantity", d.quantity],
    ["Plant", d.plant],
    ["Need by", d.need_by],
    ["Urgency", d.urgency],
    ...(d.estimated_unit_price
      ? [["Est. price", "₹" + inr(d.estimated_unit_price)]]
      : []),
  ];

  return (
    <>
      <PageHead
        title="Raise a purchase request"
        sub="Tell me what you need - I’ll ask only for anything missing."
      />
      <div className="chatgrid">
        <div className="card chatCard">
          <div id="log" ref={log}>
            {msgs.map((m, i) => (
              <div key={i} className={"m " + (m.from === "me" ? "u" : "")}>
                {m.from === "bot" && <div className="av">✦</div>}
                <div className={"bub " + (m.streaming ? "streaming" : "")}>
                  {bold(m.t)}
                  {m.streaming && <span className="streamCaret" />}
                </div>
              </div>
            ))}
            {typing && (
              <div className="m">
                <div className="av">✦</div>
                <div className="typing">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            )}
          </div>
          <div className="chips">
            {chips.map((c) => (
              <button key={c} onClick={() => send(c)}>
                {c}
              </button>
            ))}
          </div>
          <div className="composer">
            <input
              value={text}
              placeholder="Describe what you need…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            />
            <button
              className="sendButton"
              disabled={busy || !text.trim()}
              onClick={() => send()}
              aria-label="Send message"
            >
              ↑
            </button>
          </div>
          {done && (
            <div className="callout ok" style={{ margin: "12px 0 0" }}>
              <div className="row">
                <b>✅ PR created.</b>
                <div className="sp" />
                <Link className="btn p" href="/workspace">
                  Open Buyer workspace →
                </Link>
              </div>
            </div>
          )}
        </div>
        <div className="card sum">
          <div className="summaryHead">
            <div>
              <h3>Your request</h3>
              <p className="hint">Updated live</p>
            </div>
            <span
              className={Object.keys(d).length ? "liveBadge live" : "liveBadge"}
            >
              Live
            </span>
          </div>
          {rows.map(([k, v]) => (
            <div className="li" key={k}>
              <span className="k">{k}</span>
              <span className={v ? "ok" : "no"}>{v || "—"}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
