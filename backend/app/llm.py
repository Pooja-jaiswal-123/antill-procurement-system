"""Thin Groq wrapper. Optional: everything that uses it has a deterministic fallback except policy-document reading."""
import os, json, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")

MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
API_URL = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")

def available(): return bool(os.environ.get("GROQ_API_KEY"))

def complete(system, user, max_tokens=1500):
    if not available(): raise RuntimeError("GROQ_API_KEY not set")
    import httpx

    response = httpx.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    content = message.get("content")
    if content:
        return content
    raise RuntimeError("Groq returned an empty response")

def complete_json(system, user, max_tokens=1000):
    t = complete(system, user, max_tokens)
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r"\{", t):
        try:
            value, end = decoder.raw_decode(t, match.start())
            if isinstance(value, dict):
                candidates.append(value)
        except json.JSONDecodeError:
            pass
    if not candidates:
        raise RuntimeError("Groq returned no JSON object")
    return max(candidates, key=lambda value: len(json.dumps(value)))
