"""OpenAI-compatible LLM tool (chat + vision), driven by app.config.settings."""

import base64
import json
from typing import Optional

from app import metrics
from app.config import settings

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def available() -> bool:
    return bool(settings.llm_ready and OpenAI is not None)


def _client() -> "OpenAI":
    kwargs = {"api_key": settings.llm_api_key,
              "default_headers": {"User-Agent": settings.http_user_agent}}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    return OpenAI(**kwargs)


# Some gateways/models require the literal lowercase word "json" in the messages
# to accept response_format=json_object (else a 400). Guarantee it defensively.
_JSON_NUDGE = "\n\nRespond with a single valid json object only."


def chat_json(system: str, user: str, model: Optional[str] = None) -> dict:
    resp = _client().chat.completions.create(
        model=model or settings.llm_model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user + _JSON_NUDGE}],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    _record(resp)
    return json.loads(resp.choices[0].message.content)


def vision_json(system: str, user: str, image_path: str) -> dict:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    resp = _client().chat.completions.create(
        model=settings.vision_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user + _JSON_NUDGE},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    _record(resp)
    return json.loads(resp.choices[0].message.content)


def _record(resp):
    u = getattr(resp, "usage", None)
    metrics.add_llm(getattr(u, "prompt_tokens", 0) if u else 0,
                    getattr(u, "completion_tokens", 0) if u else 0)
