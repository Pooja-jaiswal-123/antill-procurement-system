"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, toast } from "../lib/api";

const NAV = [
  ["Workspace", [["/chat", "✦", "Raise request"]]],
  [
    "Procurement",
    [
      ["/workspace", "▦", "Buyer workspace"],
      ["/preferred", "★", "Preferred suppliers"],
      ["/contracts", "▤", "Rate contracts"],
      ["/policy", "◫", "Policy"],
    ],
  ],
  [
    "Administration",
    [
      ["/audit", "◷", "Audit log"],
      ["/data", "◇", "Master data"],
    ],
  ],
];

export default function Shell({ children }) {
  const path = usePathname();
  const [who, setWho] = useState("");
  const [savedWho, setSavedWho] = useState("");
  const [llm, setLlm] = useState(null);

  useEffect(() => {
    const name = localStorage.getItem("who") || "";
    setWho(name);
    setSavedWho(name);
    api("/health")
      .then((h) => setLlm(h.llm ? "on" : "off"))
      .catch(() => setLlm("down"));
  }, []);

  function saveName() {
    const name = who.trim();
    if (!name) {
      toast("Please enter your name", true);
      return;
    }
    localStorage.setItem("who", name);
    setSavedWho(name);
    setWho(name);
    toast("Profile saved successfully");
  }

  return (
    <>
      <aside>
        <div className="brand">
          <div className="brandMark">C</div>
          <div>
            <strong>Corvo</strong>
            <span>Procure</span>
          </div>
        </div>
        <div className="navArea">
          {NAV.map(([sec, items]) => (
            <div className="navGroup" key={sec}>
              <div className="sec">{sec}</div>
              {items.map(([href, ic, label]) => (
                <Link
                  key={href}
                  href={href}
                  className={"nv " + (path.startsWith(href) ? "on" : "")}
                >
                  <span className="navIcon">{ic}</span>
                  <span>{label}</span>
                </Link>
              ))}
            </div>
          ))}
        </div>
        <div className="profileCard">
          <div className="profileStatus">
            <span
              className={
                "statusDot " +
                (llm === "on" ? "online" : llm === "down" ? "offline" : "")
              }
            />
            {llm === "on"
              ? "Groq AI connected"
              : llm === "off"
                ? "Basic mode"
                : llm === "down"
                  ? "Backend unavailable"
                  : "Checking connection"}
          </div>
          <label htmlFor="profileName">Your name</label>
          <div className="profileInput">
            <input
              id="profileName"
              value={who}
              placeholder="Enter your name"
              onChange={(e) => setWho(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveName()}
            />
            <button
              type="button"
              className="saveName"
              disabled={!who.trim() || who.trim() === savedWho}
              onClick={saveName}
              aria-label="Save profile name"
            >
              ✓
            </button>
          </div>
          {savedWho && (
            <div className="savedName">
              Signed in as <b>{savedWho}</b>
            </div>
          )}
        </div>
      </aside>
      <div className="wrap">{children}</div>
    </>
  );
}
