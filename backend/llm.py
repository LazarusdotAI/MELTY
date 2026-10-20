import os
import json
import time
import asyncio
from openai import AsyncOpenAI
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core import db, now, new_id, logger
from budget import reserve, settle

# provider key -> (label, litellm provider, model env, price envs)
CATALOG = {
    "kimi": {"label": "Kimi K3", "vendor": "Hugging Face", "model": os.environ["KIMI_MODEL"],
             "price": (float(os.environ["KIMI_INPUT_PRICE"]), float(os.environ["KIMI_OUTPUT_PRICE"]))},
    "claude": {"label": "Claude Sonnet 5.5", "vendor": "anthropic", "model": os.environ["FALLBACK_MODEL"],
               "price": (float(os.environ["FALLBACK_INPUT_PRICE"]), float(os.environ["FALLBACK_OUTPUT_PRICE"]))},
    "openai": {"label": "GPT-6.1 Sol", "vendor": "openai", "model": os.environ["OPENAI_MODEL"],
               "price": (float(os.environ["OPENAI_INPUT_PRICE"]), float(os.environ["OPENAI_OUTPUT_PRICE"]))},
    "gemini": {"label": "Gemini 4 Argon", "vendor": "gemini", "model": os.environ["GEMINI_MODEL"],
               "price": (float(os.environ["GEMINI_INPUT_PRICE"]), float(os.environ["GEMINI_OUTPUT_PRICE"]))},
}
ORDER = ["kimi", "claude", "openai", "gemini"]
_down = {}
_errors = {}


class LLMError(Exception):
    pass


# providers called directly with the user's own key: provider -> (key env, base url env or None)
DIRECT = {"kimi": ("HF_TOKEN", "KIMI_BASE_URL"), "openai": ("OPENAI_API_KEY", None), "gemini": ("GOOGLE_API_KEY", "GEMINI_BASE_URL")}
BILLING = {"kimi": "Your Hugging Face token", "openai": "Your OpenAI key", "gemini": "Your Google AI Studio key"}


def _client(p):
    key, base = DIRECT[p]
    return AsyncOpenAI(api_key=os.environ[key], base_url=os.environ[base] if base else None, timeout=900)


def configured(p: str) -> bool:
    if p in DIRECT:
        return bool(os.environ.get(DIRECT[p][0])) and (p == "kimi" or os.environ.get("FALLBACK_ENABLED") == "true")
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("FALLBACK_ENABLED") == "true"


def _text_len(m) -> int:
    c = m.get("content")
    if isinstance(c, list):
        return sum(len(x.get("text", "")) if x.get("type") == "text" else 6000 for x in c) + len(json.dumps(m.get("tool_calls") or []))
    return len(json.dumps(m))


def estimate_cost(p: str, messages: list, tools, max_tokens: int) -> float:
    chars = sum(_text_len(m) for m in messages) + len(json.dumps(tools or []))
    pin, pout = CATALOG[p]["price"]
    return round(((chars / 3.0 + 500) * pin + max_tokens * pout) / 1_000_000, 6)


def actual_cost(p: str, tin: int, tout: int) -> float:
    pin, pout = CATALOG[p]["price"]
    return round((tin * pin + tout * pout) / 1_000_000, 6)


async def preferred() -> str:
    s = await db.settings.find_one({"id": "settings"}, {"_id": 0, "preferred_model": 1}) or {}
    return s.get("preferred_model") if s.get("preferred_model") in CATALOG else "kimi"


async def chain() -> list:
    first = await preferred()
    order = [first] + [p for p in ORDER if p != first]
    return [p for p in order if configured(p) and time.time() >= _down.get(p, 0)]


async def provider_status() -> dict:
    pref = await preferred()
    active = (await chain() or [None])[0]
    models = [{"key": p, **{k: CATALOG[p][k] for k in ("label", "vendor", "model")},
               "price_per_m": CATALOG[p]["price"], "configured": configured(p),
               "available": configured(p) and time.time() >= _down.get(p, 0), "last_error": _errors.get(p),
               "billing": BILLING.get(p, "Emergent universal key")} for p in ORDER]
    return {"preferred": pref, "active": active, "models": models}


def _resp_content(c):
    if not isinstance(c, list):
        return c
    return [{"type": "input_text", "text": x["text"]} if x.get("type") == "text"
            else {"type": "input_image", "image_url": x["image_url"]["url"]} for x in c]


def _resp_input(messages):
    items = []
    for m in messages[1:]:
        if m["role"] == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": _flat(m["content"])})
            continue
        if m.get("content"):
            items.append({"role": m["role"], "content": _resp_content(m["content"]) if m["role"] == "user" else _flat(m["content"])})
        for tc in m.get("tool_calls") or []:
            items.append({"type": "function_call", "call_id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]})
    return items


async def _call_openai(messages, tools, max_tokens):
    # GPT-6.1 Sol only supports tools + reasoning on the Responses API
    kw = {"model": CATALOG["openai"]["model"], "instructions": messages[0]["content"], "input": _resp_input(messages),
          "max_output_tokens": max_tokens, "reasoning": {"effort": os.environ["OPENAI_REASONING_EFFORT"]}, "store": False}
    if tools:
        kw["tools"] = [{"type": "function", **t["function"]} for t in tools]
    r = await _client("openai").responses.create(**kw)
    text, calls = "", []
    for o in r.output:
        if o.type == "message":
            text += "".join(c.text for c in o.content if c.type == "output_text")
        elif o.type == "function_call":
            calls.append({"id": o.call_id, "type": "function", "function": {"name": o.name, "arguments": o.arguments}})
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = calls
    finish = "tool_calls" if calls else ("length" if r.status == "incomplete" else "stop")
    return msg, r.usage.input_tokens, r.usage.output_tokens, finish


async def _call_direct(p, messages, tools, max_tokens):
    if p == "openai":
        return await _call_openai(messages, tools, max_tokens)
    kw = {"model": CATALOG[p]["model"], "messages": messages, "max_completion_tokens": max_tokens}
    if p == "kimi":
        kw["extra_body"] = {"reasoning_effort": os.environ["KIMI_REASONING_EFFORT"]}
    if tools:
        kw["tools"] = tools
    r = await _client(p).chat.completions.create(**kw)
    m = r.choices[0].message.model_dump(exclude_none=True)
    m["role"] = "assistant"
    return m, r.usage.prompt_tokens or 0, r.usage.completion_tokens or 0, r.choices[0].finish_reason


def _flat(c):
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if x.get("type") == "text") + " [screenshot omitted: backup model has no image input here]"
    return c


def _clean(m: dict) -> dict:
    out = {k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "tool_call_id")}
    if "content" in out:
        out["content"] = _flat(out["content"])
    return out


async def _call_emergent(p, messages, tools, max_tokens):
    msgs = [_clean(m) for m in messages]
    if msgs[-1]["role"] == "user":
        init, um = msgs[:-1], UserMessage(text=msgs[-1]["content"])
    else:
        init, um = msgs, None
    tok_key = "max_tokens"
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=new_id(), system_message=msgs[0]["content"],
                   initial_messages=init).with_model(CATALOG[p]["vendor"], CATALOG[p]["model"]).with_params(
        **{tok_key: max_tokens, "timeout": 900})
    if tools:
        chat.with_tools(tools, tool_choice="auto")
    resp = await chat.send_message_with_tools(um)
    return dict(chat.messages[-1]), resp.usage.input_tokens, resp.usage.output_tokens, resp.finish_reason


async def complete(messages: list, tools, max_tokens: int, meta: dict) -> dict:
    """One paid AI call: reserve → call → settle → record. Falls through the model chain on errors."""
    providers = await chain()
    if not providers:
        raise LLMError(f"No AI model available: {_errors}")
    errors = []
    for p in providers:
        est = estimate_cost(p, messages, tools, max_tokens)
        rid = await reserve(est, {"project_id": meta.get("project_id"), "generation_id": meta.get("generation_id")})
        started = time.time()
        rec = {"id": new_id(), "provider": p, "model": CATALOG[p]["model"], "reserved": est, "created_at": now(), **meta}
        try:
            coro = _call_direct(p, messages, tools, max_tokens) if p in DIRECT else _call_emergent(p, messages, tools, max_tokens)
            msg, tin, tout, finish = await asyncio.wait_for(coro, timeout=900)
        except Exception as e:
            timed_out = isinstance(e, asyncio.TimeoutError) or "timeout" in str(e).lower()
            charge = est if timed_out else 0.0
            await settle(rid, charge)
            err = str(e)[:400]
            errors.append(f"{p}: {err}")
            _errors[p] = err
            _down[p] = time.time() + 600
            await db.ai_calls.insert_one({**rec, "status": "error", "error": err, "cost": charge,
                                          "seconds": round(time.time() - started, 1)})
            logger.warning("LLM call failed (%s): %s", p, err)
            continue
        cost = actual_cost(p, tin, tout)
        await settle(rid, cost)
        _errors.pop(p, None)
        await db.ai_calls.insert_one({**rec, "status": "ok", "input_tokens": tin, "output_tokens": tout,
                                      "cost": cost, "finish_reason": finish, "seconds": round(time.time() - started, 1)})
        return {"message": msg, "provider": p, "label": CATALOG[p]["label"], "model": CATALOG[p]["model"],
                "cost": cost, "input_tokens": tin, "output_tokens": tout, "finish_reason": finish}
    raise LLMError("; ".join(errors))
