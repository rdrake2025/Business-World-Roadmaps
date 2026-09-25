"""Live answer-engine clients.

Deliberately built on ``requests`` rather than vendor SDKs: one dependency,
no version pinning conflicts, and the wire format for all four providers is
simple JSON. Each client fails soft — a provider outage degrades the audit
to the remaining engines instead of killing the run.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from .base import AnswerEngine, EngineAnswer

# Asking for a short, list-shaped recommendation mirrors how a real buyer
# prompts an assistant, and keeps token cost per probe near zero.
SYSTEM_PROMPT = (
    "You are helping a consumer find a local service provider. "
    "Answer as you normally would: name specific real businesses you would "
    "recommend, as a short numbered list with one line each. "
    "If you are not aware of specific local businesses, say so plainly."
)


def _post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> tuple[dict | None, str]:
    """POST returning (json, error). Never raises."""
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        return resp.json(), ""
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"bad JSON: {exc}"


class OpenAIEngine(AnswerEngine):
    """ChatGPT, as a customer meets it: searching the web, from their town.

    This used to ask a small model with no search at all, so it answered
    from memory, and a model's memory of local businesses is thin and often
    invented. ChatGPT itself searches the web for local questions
    (BrightLocal found it cites business sites, mentions and directories,
    through Bing). The Responses API's web_search tool does the same, from
    an approximate location, and returns the sources it used.
    """

    name = "openai"
    label = "ChatGPT"
    weight = 1.6  # largest consumer assistant audience

    def __init__(self, api_key: str | None = None, model: str = "gpt-5-mini",
                 timeout: int = 90):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def ask(self, prompt: str) -> EngineAnswer:
        from ..geo import user_location

        t0 = time.time()
        tool: dict[str, Any] = {"type": "web_search"}
        if self.city or self.state:
            tool["user_location"] = user_location(self.city, self.state)
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": SYSTEM_PROMPT,
            "input": prompt,
            "tools": [tool],
            "max_output_tokens": 2500,
        }
        if self.model.startswith(("gpt-5", "o")):
            payload["reasoning"] = {"effort": "low"}
        data, err = _post("https://api.openai.com/v1/responses", self._headers(),
                          payload, self.timeout)
        ms = int((time.time() - t0) * 1000)
        if err:
            if err.startswith("HTTP 4"):
                # A model or account without the tool: answer, but say it
                # is from memory so nothing quotes it as ChatGPT's view.
                return self._from_memory(prompt, t0)
            return EngineAnswer(text="", sources=[], latency_ms=ms, error=err)
        text, sources, searched = parse_responses_output(data or {})
        return EngineAnswer(text=text, sources=sources, latency_ms=ms, grounded=searched)

    def _from_memory(self, prompt: str, t0: float) -> EngineAnswer:
        data, err = _post(
            "https://api.openai.com/v1/chat/completions", self._headers(),
            {"model": "gpt-4o-mini",
             "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
             "temperature": 0.3, "max_tokens": 600},
            self.timeout)
        ms = int((time.time() - t0) * 1000)
        if err:
            return EngineAnswer(text="", sources=[], latency_ms=ms, error=err)
        text = (data or {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        return EngineAnswer(text=text, sources=[], latency_ms=ms, grounded=False)


def parse_responses_output(data: dict[str, Any]) -> tuple[str, list[str], bool]:
    """(answer text, cited URLs, whether it searched) from a Responses API reply."""
    parts: list[str] = []
    sources: list[str] = []
    searched = False
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            searched = True
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "output_text":
                continue
            parts.append(block.get("text", ""))
            for note in block.get("annotations") or []:
                if isinstance(note, dict) and note.get("type") == "url_citation" \
                        and note.get("url") and note["url"] not in sources:
                    sources.append(note["url"])
    if not parts and isinstance(data.get("output_text"), str):
        parts.append(data["output_text"])
    return "\n".join(p for p in parts if p), sources, searched or bool(sources)


class AnthropicEngine(AnswerEngine):
    """Claude with its web search tool, from the business's town.

    Capped at two searches a question: enough for a local recommendation,
    and the cost ($10 per 1,000 searches plus the tokens results add) stays
    small. Answers where Claude chose not to search are marked as from
    memory.
    """

    name = "anthropic"
    label = "Claude"
    weight = 1.2

    def __init__(self, api_key: str | None = None,
                 model: str = "claude-haiku-4-5-20251001", timeout: int = 90):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, prompt: str) -> EngineAnswer:
        from ..geo import user_location

        t0 = time.time()
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search",
                                "max_uses": 2}
        if self.city or self.state:
            tool["user_location"] = user_location(self.city, self.state)
        payload: dict[str, Any] = {
            "model": self.model, "max_tokens": 1024, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}], "tools": [tool],
        }
        data, err = _post("https://api.anthropic.com/v1/messages", headers,
                          payload, self.timeout)
        if err and err.startswith("HTTP 400"):
            # Web search switched off for the organisation: ask without it.
            payload.pop("tools")
            data, err = _post("https://api.anthropic.com/v1/messages", headers,
                              payload, self.timeout)
        ms = int((time.time() - t0) * 1000)
        if err:
            return EngineAnswer(text="", sources=[], latency_ms=ms, error=err)
        text, sources, searched = parse_claude_content((data or {}).get("content", []))
        return EngineAnswer(text=text, sources=sources, latency_ms=ms, grounded=searched)


def parse_claude_content(blocks: list[Any]) -> tuple[str, list[str], bool]:
    """(answer text, cited URLs, whether a search returned results)."""
    parts: list[str] = []
    sources: list[str] = []
    searched = False
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
            for cite in block.get("citations") or []:
                if isinstance(cite, dict) and cite.get("url") and cite["url"] not in sources:
                    sources.append(cite["url"])
        elif kind == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, list):
                searched = True
                for result in content:
                    if isinstance(result, dict) and result.get("url") \
                            and result["url"] not in sources:
                        sources.append(result["url"])
    return "".join(parts).strip(), sources, searched


class PerplexityEngine(AnswerEngine):
    name = "perplexity"
    label = "Perplexity"
    weight = 1.3  # citation-heavy: the best signal for source-level visibility

    def __init__(self, api_key: str | None = None, model: str = "sonar", timeout: int = 60):
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, prompt: str) -> EngineAnswer:
        t0 = time.time()
        data, err = _post(
            "https://api.perplexity.ai/chat/completions",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 600,
            },
            self.timeout,
        )
        ms = int((time.time() - t0) * 1000)
        if err:
            return EngineAnswer(text="", sources=[], latency_ms=ms, error=err)
        payload = data or {}
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Perplexity returns the URLs it grounded on; these are real citations.
        sources = payload.get("citations") or [
            s.get("url", "") for s in payload.get("search_results", []) if isinstance(s, dict)
        ]
        return EngineAnswer(text=text, sources=[s for s in sources if s], latency_ms=ms,
                            grounded=True)


class GoogleAIOverviewEngine(AnswerEngine):
    """Google AI Overviews, captured through a SERP API (Serper.dev).

    Google has no first-party API for AI Overviews, so we read them through a
    SERP provider. This is the highest-value surface for local intent because
    it sits on top of the query volume that still goes to Google.
    """

    name = "google_aio"
    label = "Google AI Overviews"
    weight = 1.8

    def __init__(self, api_key: str | None = None, timeout: int = 60, gl: str = "us"):
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")
        self.timeout = timeout
        self.gl = gl

    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, prompt: str) -> EngineAnswer:
        t0 = time.time()
        data, err = _post(
            "https://google.serper.dev/search",
            {"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            {"q": prompt, "gl": self.gl, "num": 10},
            self.timeout,
        )
        ms = int((time.time() - t0) * 1000)
        if err:
            return EngineAnswer(text="", sources=[], latency_ms=ms, error=err)

        payload = data or {}
        parts: list[str] = []
        sources: list[str] = []

        # AI Overview block, when Serper surfaces one.
        aio = payload.get("aiOverview") or payload.get("answerBox") or {}
        if isinstance(aio, dict):
            for key in ("answer", "snippet", "textBlocks", "description"):
                val = aio.get(key)
                if isinstance(val, str) and val:
                    parts.append(val)
                elif isinstance(val, list):
                    for blk in val:
                        if isinstance(blk, dict) and blk.get("snippet"):
                            parts.append(str(blk["snippet"]))
                        elif isinstance(blk, str):
                            parts.append(blk)
            for ref in aio.get("references", []) or []:
                if isinstance(ref, dict) and ref.get("link"):
                    sources.append(ref["link"])

        # The local pack is what actually wins local service intent.
        for place in (payload.get("places") or [])[:6]:
            if isinstance(place, dict) and place.get("title"):
                rating = place.get("rating")
                suffix = f" ({rating} stars)" if rating else ""
                parts.append(f"- **{place['title']}**{suffix}")
                if place.get("website"):
                    sources.append(place["website"])

        for org in (payload.get("organic") or [])[:5]:
            if isinstance(org, dict):
                if org.get("title"):
                    parts.append(f"- **{org['title']}**")
                if org.get("link"):
                    sources.append(org["link"])

        return EngineAnswer(text="\n".join(parts), sources=sources, latency_ms=ms,
                            grounded=True)


ENGINE_CLASSES = {
    "openai": OpenAIEngine,
    "anthropic": AnthropicEngine,
    "perplexity": PerplexityEngine,
    "google_aio": GoogleAIOverviewEngine,
}


def build_engines(names: list[str], business_name: str = "", vertical: str = "default",
                  timeout: int = 60, city: str = "", state: str = "") -> list[AnswerEngine]:
    """Instantiate the requested engines, dropping any we lack credentials for."""
    from .mock import MockEngine

    engines: list[AnswerEngine] = []
    for name in names:
        if name == "mock":
            engines.append(MockEngine(business_name=business_name, vertical=vertical))
            continue
        cls = ENGINE_CLASSES.get(name)
        if not cls:
            continue
        eng = cls(timeout=max(timeout, 90) if name in {"openai", "anthropic"} else timeout)
        if eng.available():
            engines.append(eng.locate(city, state))
    if not engines:
        engines.append(MockEngine(business_name=business_name, vertical=vertical))
    return engines
