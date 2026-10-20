# Offline: the coding loop's history compaction (modagent.compact). Synthetic history only.
import ast
import copy
import json
from pathlib import Path

MODAGENT = Path(__file__).resolve().parents[1] / "modagent.py"


def compact():
    """Exec only compact() and its constants: importing modagent needs MongoDB and LLM keys."""
    names = {"TRIM_OVER", "TRIM_KEEP", "compact"}
    tree = ast.parse(MODAGENT.read_text(encoding="utf-8"))
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names) or
            (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))]
    ns = {"json": json}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(MODAGENT), "exec"), ns)
    return ns["compact"]


def turn(n, big):
    calls = [{"id": f"w{n}", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "init.lua", "content": "x" * big})}},
             {"id": f"b{n}", "type": "function", "function": {"name": "build", "arguments": "{}"}}]
    return [{"role": "assistant", "content": f"turn {n}", "tool_calls": calls},
            {"role": "tool", "tool_call_id": f"w{n}", "content": "OK wrote init.lua"},
            {"role": "tool", "tool_call_id": f"b{n}", "content": "L" * 4000},
            {"role": "user", "content": [{"type": "text", "text": f"Screenshot {n}"}, {"type": "image_url", "image_url": {"url": "data:..."}}]}]


def session(turns, big=6000):
    msgs = [{"role": "system", "content": "S" * 9000}, {"role": "user", "content": "task"}]
    for n in range(turns):
        msgs += turn(n, big)
    return msgs


def test_old_turns_shrink_recent_turns_stay_whole():
    msgs = session(5)
    before = copy.deepcopy(msgs)
    assert compact()(msgs) > 0
    asst = [i for i, m in enumerate(msgs) if m["role"] == "assistant"]
    assert msgs[asst[-2]:] == before[asst[-2]:]  # last two turns untouched
    assert msgs[:2] == before[:2]  # system prompt and task untouched
    old = msgs[asst[0]]
    assert json.loads(old["tool_calls"][0]["function"]["arguments"])["path"] == "init.lua"  # still valid JSON
    assert "read_file" in json.loads(old["tool_calls"][0]["function"]["arguments"])["content"]
    assert [tc["id"] for tc in old["tool_calls"]] == ["w0", "b0"]  # tool call ids still pair with results
    assert "trimmed to save tokens" in msgs[asst[0] + 2]["content"]
    assert isinstance(msgs[asst[0] + 3]["content"], str)  # old screenshot became text
    assert compact()(msgs) == 0  # stable: a second pass changes nothing (prompt cache stays valid)


def test_short_sessions_are_untouched():
    msgs = session(2)
    before = copy.deepcopy(msgs)
    assert compact()(msgs) == 0 and msgs == before


def sent_chars(msgs):
    return sum(len(json.dumps(m)) for m in msgs)


def test_savings_over_a_full_job():
    """Characters sent across a 12-turn job, with and without compaction (each turn resends the history)."""
    c, plain, packed, msgs_a, msgs_b = compact(), 0, 0, session(0), session(0)
    for n in range(12):
        msgs_a += turn(n, 6000)
        msgs_b += turn(n, 6000)
        c(msgs_b)
        plain += sent_chars(msgs_a)
        packed += sent_chars(msgs_b)
    saving = 1 - packed / plain
    print(f"\nchars sent over 12 turns: {plain:,} -> {packed:,} ({saving:.0%} less)")
    assert saving > 0.5
