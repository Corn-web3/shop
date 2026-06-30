"""Thin OpenAI-compatible client shared by the copy + critic agents.

Everything is driven by env vars so a reviewer can point it at any
OpenAI-compatible endpoint. If no key is configured, `available()` returns
False and callers fall back to a deterministic offline path so the pipeline
still runs end-to-end (a hard requirement from the README: the service must
start and behave sensibly even without keys).
"""

import base64
import json
import os
from typing import Optional

try:
    from openai import OpenAI
except Exception:  # SDK not installed yet
    OpenAI = None


def _env(*names: str) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


LLM_BASE_URL = _env("LLM_BASE_URL", "OPENAI_BASE_URL")
LLM_API_KEY = _env("LLM_API_KEY", "OPENAI_API_KEY")
LLM_MODEL = _env("LLM_MODEL") or "gpt-4o-mini"
VISION_MODEL = _env("VISION_MODEL") or LLM_MODEL


def available() -> bool:
    return bool(LLM_API_KEY and OpenAI is not None)


def _client() -> "OpenAI":
    kwargs = {"api_key": LLM_API_KEY}
    if LLM_BASE_URL:
        kwargs["base_url"] = LLM_BASE_URL
    return OpenAI(**kwargs)


def chat_json(system: str, user: str, model: Optional[str] = None) -> dict:
    """Single-turn chat that must return a JSON object."""
    resp = _client().chat.completions.create(
        model=model or LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


def vision_json(system: str, user: str, image_path: str) -> dict:
    """Ask a vision model to inspect an image and return a JSON verdict."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    resp = _client().chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(resp.choices[0].message.content)
