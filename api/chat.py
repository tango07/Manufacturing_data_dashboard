"""Chat service: turns a conversation into an answer, either all at once or as a stream.

Request body (JSON):
  {"messages": [{"role": "user" | "assistant", "content": "..."}, ...]}   # full conversation, last is the user
  or {"question": "..."}                                                  # a single question
  or {"question_id": "Q1" ... "Q5"}                                       # a suggested leadership question

Decisions, in order:
  1. Malformed or empty input is rejected.
  2. A named plant that is not in the data is answered without a model call.
  3. Without a key and model, a suggested leadership question gets the pipeline's own answer, and any other
     question gets a clear "not configured" reply. No key is ever returned.
  4. Otherwise the model answers from the data context, with the conversation so far.
  5. If the provider fails, a suggested leadership question still gets the pipeline's answer; the error
     message shown to the user never contains the key or request text.
"""

from __future__ import annotations

from typing import Callable, Iterator, Mapping

from api.assistant_core import (LEADERSHIP_IDS, MissingApiKey, MissingModel, ProviderError, build_chat_request,
                                call_llm, get_api_key, get_base_url, get_model, leadership_answer,
                                normalize_messages, pre_check, stream_llm)

NOT_CONFIGURED = ("The assistant is not connected to a language model yet. Add LLM_API_KEY and LLM_MODEL to the "
                  ".env file and restart the server. The five suggested leadership questions still work from the "
                  "pipeline's results.")

LLMCall = Callable[[dict, str, str], str]
LLMStream = Callable[[dict, str, str], Iterator[str]]


def _resolve(body: Mapping, payload: dict) -> tuple[list[dict], str]:
    """Return (messages, question_id). Raises ValueError with a user-facing message when input is unusable."""
    qid = str(body.get("question_id") or "").upper()
    if "messages" in body:
        messages = normalize_messages(body.get("messages"))
        if not messages:
            raise ValueError("Send a question.")
        return messages, qid if qid in LEADERSHIP_IDS else ""
    question = str(body.get("question") or "").strip()
    if not question and qid in LEADERSHIP_IDS:
        question = payload["leadership"][qid]["question"]
    if not question:
        raise ValueError("Send a question.")
    messages = normalize_messages([{"role": "user", "content": question}])
    if not messages:
        raise ValueError("Send a question.")
    return messages, qid if qid in LEADERSHIP_IDS else ""


def _plan(body: Mapping, payload: dict, env: Mapping) -> tuple[dict | None, dict | None]:
    """Return (immediate_reply, model_plan). Exactly one of them is set."""
    try:
        messages, qid = _resolve(body, payload)
    except ValueError as exc:
        return {"mode": "error", "answer": str(exc)}, None

    last = messages[-1]["content"]
    refusal = pre_check(last, payload)
    if refusal:
        return {"mode": "refused", "answer": refusal["answer"]}, None

    try:
        key = get_api_key(env)
        model = get_model(env)
    except (MissingApiKey, MissingModel):
        if qid:
            return {"mode": "pipeline", "answer": leadership_answer(qid, payload), "question_id": qid}, None
        return {"mode": "unavailable", "answer": NOT_CONFIGURED}, None

    return None, {"request": build_chat_request(messages, payload, model), "key": key,
                  "url": get_base_url(env), "qid": qid}


def _fallback(qid: str, payload: dict, note: str) -> dict:
    return {"mode": "pipeline", "answer": leadership_answer(qid, payload), "question_id": qid, "note": note}


def answer(body: Mapping, payload: dict, env: Mapping, llm_call: LLMCall | None = None) -> dict:
    """Complete reply in one response."""
    immediate, plan = _plan(body, payload, env)
    if immediate:
        return immediate
    llm_call = llm_call or call_llm
    try:
        text = (llm_call(plan["request"], plan["key"], plan["url"]) or "").strip()
    except ProviderError as exc:
        if plan["qid"]:
            return _fallback(plan["qid"], payload, f"{exc} Showing the pipeline's answer instead.")
        return {"mode": "error", "answer": str(exc)}
    if not text:
        if plan["qid"]:
            return _fallback(plan["qid"], payload, "The model returned no text. Showing the pipeline's answer.")
        return {"mode": "error", "answer": "The model returned no answer. Try rephrasing the question."}
    return {"mode": "llm", "answer": text, "question_id": plan["qid"] or None}


def stream(body: Mapping, payload: dict, env: Mapping, llm_stream: LLMStream | None = None) -> Iterator[dict]:
    """Yield events: {"delta": text} while the reply is produced, then exactly one {"done": True, "mode": ...}
    or {"error": message, "mode": ...}. Immediate replies are sent as a single delta."""
    immediate, plan = _plan(body, payload, env)
    if immediate:
        yield {"delta": immediate["answer"]}
        yield {"done": True, "mode": immediate["mode"], "question_id": immediate.get("question_id")}
        return
    llm_stream = llm_stream or stream_llm
    produced = False
    try:
        for chunk in llm_stream(plan["request"], plan["key"], plan["url"]):
            produced = True
            yield {"delta": chunk}
    except ProviderError as exc:
        if plan["qid"] and not produced:
            fb = _fallback(plan["qid"], payload, f"{exc} Showing the pipeline's answer instead.")
            yield {"delta": fb["answer"]}
            yield {"done": True, "mode": "pipeline", "question_id": plan["qid"], "note": fb["note"]}
            return
        yield {"error": str(exc), "mode": "error"}
        return
    if not produced:
        yield {"error": "The model returned no answer. Try rephrasing the question.", "mode": "error"}
        return
    yield {"done": True, "mode": "llm", "question_id": plan["qid"] or None}
