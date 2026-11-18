"""LLM / SLM backends.

LLM_BACKEND selects where generation happens:

  ollama      Local model served by Ollama. Defaults to a Small Language
              Model (SLM) - llama3.2:1b - that runs on a laptop CPU.
              Any Ollama model works: qwen2.5:1.5b, phi3:mini, gemma2:2b,
              or a full-size LLM such as llama3.1:8b.
  openai      Hosted LLM through the OpenAI Chat Completions API.
  extractive  No model at all: returns the best-matching retrieved passage.
              Used by the automated tests and as a graceful fallback, so the
              app still answers (with sources) when no model is reachable.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("chat_api.llm")

LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None   # any OpenAI-compatible provider
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))

SYSTEM_PROMPT = (
    "You are a teaching assistant for a NoSQL / MongoDB course. "
    "Answer ONLY from the numbered context passages. Cite passages like [1], [2]. "
    "If the context does not contain the answer, say you don't know. "
    "When LIVE DASHBOARD DATA is given, use those numbers to explain the user's own MongoDB server."
)


def build_prompt(question: str, sources: list[dict], live: str | None = None) -> str:
    ctx = "\n".join(f"[{i}] ({s['source']}) {s['text']}" for i, s in enumerate(sources, 1))
    live_block = f"LIVE DASHBOARD DATA (current readings from the user's MongoDB):\n{live}\n\n" if live else ""
    return f"{live_block}Context:\n{ctx or '(no passages retrieved)'}\n\nQuestion: {question}\nAnswer:"


def _extractive(question: str, sources: list[dict], live: str | None = None) -> str:
    if not sources:
        return "I don't know - no relevant passages are stored yet. Ingest documents first."
    top = sources[0]
    answer = f"{top['text']} [1]"
    if live:
        answer += "\n\nYour current readings:\n" + live
    return answer


def _ollama(messages: list[dict]) -> str:
    import requests

    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": TEMPERATURE, "num_predict": MAX_TOKENS},
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _openai(messages: list[dict]) -> str:
    from openai import OpenAI

    resp = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL).chat.completions.create(
        model=OPENAI_MODEL, messages=messages, max_tokens=MAX_TOKENS, temperature=TEMPERATURE
    )
    return resp.choices[0].message.content


def generate(question: str, sources: list[dict], history: list[dict], live: str | None = None) -> tuple[str, str]:
    """Return (answer, backend_actually_used). `live` = optional dashboard metrics for this question."""
    if LLM_BACKEND == "extractive":
        return _extractive(question, sources, live), "extractive"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                {"role": "user", "content": build_prompt(question, sources, live)}]
    try:
        if LLM_BACKEND == "openai" and OPENAI_API_KEY:
            return _openai(messages), f"openai:{OPENAI_MODEL}"
        return _ollama(messages), f"ollama:{OLLAMA_MODEL}"
    except Exception as exc:  # model down -> still answer from retrieved text
        logger.warning("LLM call failed (%s); falling back to extractive answer", exc)
        return _extractive(question, sources, live), "extractive-fallback"
