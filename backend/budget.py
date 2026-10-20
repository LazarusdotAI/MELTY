import os
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError
from core import db, now, new_id, NO_ID


class BudgetExceeded(Exception):
    def __init__(self, needed: float, remaining: float):
        self.needed = needed
        self.remaining = remaining
        super().__init__(f"Daily AI budget insufficient: need ${needed:.4f}, remaining ${remaining:.4f}")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get_settings() -> dict:
    s = await db.settings.find_one({"id": "settings"}, NO_ID) or {}
    return {
        "daily_ceiling": float(s.get("daily_ceiling", os.environ["DAILY_BUDGET_USD"])),
        "generation_ceiling": float(s.get("generation_ceiling", os.environ["GENERATION_BUDGET_USD"])),
        "target": 10.0,
    }


async def _ensure_day(day: str):
    try:
        await db.budget_days.update_one(
            {"day": day}, {"$setOnInsert": {"day": day, "spent": 0.0, "reserved": 0.0}}, upsert=True
        )
    except DuplicateKeyError:
        pass


async def day_state() -> dict:
    day = today()
    await _ensure_day(day)
    d = await db.budget_days.find_one({"day": day}, NO_ID)
    cap = (await get_settings())["daily_ceiling"]
    remaining = max(0.0, cap - d["spent"] - d["reserved"])
    return {"day": day, "ceiling": cap, "spent": d["spent"], "reserved": d["reserved"], "remaining": remaining}


async def reserve(amount: float, meta: dict) -> str:
    """Atomically reserve `amount` USD against today's ceiling; raises BudgetExceeded."""
    day = today()
    await _ensure_day(day)
    cap = (await get_settings())["daily_ceiling"]
    ok = await db.budget_days.find_one_and_update(
        {"day": day, "$expr": {"$lte": [{"$add": ["$spent", "$reserved", amount]}, cap]}},
        {"$inc": {"reserved": amount}},
    )
    if not ok:
        st = await day_state()
        raise BudgetExceeded(amount, st["remaining"])
    rid = new_id()
    await db.reservations.insert_one(
        {"id": rid, "day": day, "amount": amount, "status": "open", "created_at": now(), **meta}
    )
    return rid


async def settle(rid: str, actual: float):
    r = await db.reservations.find_one_and_update(
        {"id": rid, "status": "open"}, {"$set": {"status": "settled", "actual": actual, "settled_at": now()}}
    )
    if r:
        await db.budget_days.update_one({"day": r["day"]}, {"$inc": {"reserved": -r["amount"], "spent": actual}})


async def settle_orphans():
    """Reservations left open by a crash are charged conservatively at their reserved amount."""
    async for r in db.reservations.find({"status": "open"}, NO_ID):
        await settle(r["id"], r["amount"])
