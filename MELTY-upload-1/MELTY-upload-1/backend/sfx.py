import os
import asyncio
from elevenlabs.client import AsyncElevenLabs
from core import db, now, new_id
from budget import reserve, settle
from assets import put_object, APP_NAME


def enabled() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def estimate(duration: float) -> float:
    credits = float(os.environ["ELEVENLABS_CREDITS_PER_SECOND"]) * duration
    return round(credits * float(os.environ["ELEVENLABS_USD_PER_CREDIT"]), 5)


async def generate_sfx(prompt: str, duration: float, project_id: str = "") -> dict:
    cost = estimate(duration)
    rid = await reserve(cost, {"project_id": project_id or None, "generation_id": None})
    rec = {"id": new_id(), "provider": "elevenlabs", "model": "eleven_text_to_sound_v2", "reserved": cost,
           "project_id": project_id or None, "purpose": f"sound effect: {prompt[:60]}", "created_at": now()}
    try:
        client = AsyncElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=60)
        chunks = [c async for c in client.text_to_sound_effects.convert(
            text=prompt, duration_seconds=duration, model_id="eleven_text_to_sound_v2", output_format="mp3_44100_128")]
        data = b"".join(chunks)
    except Exception as e:
        await settle(rid, 0.0)
        await db.ai_calls.insert_one({**rec, "status": "error", "error": str(e)[:300], "cost": 0.0})
        raise
    await settle(rid, cost)
    await db.ai_calls.insert_one({**rec, "status": "ok", "cost": cost, "input_tokens": 0, "output_tokens": 0,
                                  "note": "estimated from credits/second"})
    base = "".join(ch if ch.isalnum() else "_" for ch in prompt.lower())[:30].strip("_") or "sfx"
    name = f"sfx_{base}_{new_id()[:5]}.mp3"
    res = await asyncio.to_thread(put_object, f"{APP_NAME}/uploads/{new_id()}.mp3", data, "audio/mpeg")
    aid = new_id()
    await db.assets.insert_one({"id": aid, "name": name, "original_filename": name, "kind": "sfx",
                                "storage_path": res["path"], "content_type": "audio/mpeg", "size": len(data),
                                "license": "Generated with ElevenLabs (your account's commercial terms apply)",
                                "source": "elevenlabs", "prompt": prompt, "is_deleted": False, "created_at": now()})
    return {"id": aid, "name": name, "cost": cost}
