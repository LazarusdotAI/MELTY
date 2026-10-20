"""Trainer iteration_10 regressions on the TEST_TR_UI fake device (requires tr_ui_fixture.py running -> /tmp/TEST_TR_dev.json)."""
import os
import json
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parents[1] / "frontend" / ".env")
load_dotenv(HERE.parent / ".env")
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
F = Path("/tmp/TEST_TR_dev.json")
pytestmark = pytest.mark.skipif(not F.exists(), reason="tr_ui_fixture not running")


@pytest.fixture(scope="module")
def fx():
    return json.loads(F.read_text())


def ref(fx):
    return {"device_id": fx["did"], "install_dir": fx["cp"]}


# apply edge cases
def test_apply_unknown_and_build_only_off(fx):
    r = requests.post(f"{API}/trainer/apply", json={**ref(fx), "features": {"no_recoil": {"on": False}, "bogus": {"on": False}}})
    assert r.status_code == 200, r.text


def test_apply_unknown_on_400(fx):
    assert requests.post(f"{API}/trainer/apply", json={**ref(fx), "features": {"bogus": {"on": True}}}).status_code == 400


def test_apply_non_numeric_slider_400(fx):
    r = requests.post(f"{API}/trainer/apply", json={**ref(fx), "features": {"super_speed": {"on": True, "value": "fast"}}})
    assert r.status_code == 400 and "number" in r.json()["detail"]


def test_apply_non_dict_feature_value(fx):
    r = requests.post(f"{API}/trainer/apply", json={**ref(fx), "features": {"god_mode": True}})
    assert r.status_code in (200, 400, 422), r.status_code


def test_rev_strictly_increasing_ms(fx):
    revs = [requests.post(f"{API}/trainer/apply", json={**ref(fx), "features": {}}).json()["rev"] for _ in range(3)]
    assert revs[0] < revs[1] < revs[2] and revs[0] > 10 ** 12


def test_time_of_day_default(fx):
    g = requests.get(f"{API}/trainer/game", params=ref(fx)).json()
    tod = [f for f in g["features"] if f["key"] == "time_of_day"][0]
    assert tod["default"] == 12


def test_presets_device_scoped(fx):
    p = requests.post(f"{API}/trainer/presets", json={**ref(fx), "name": "TEST preset", "features": {"god_mode": {"on": True}}}).json()
    try:
        assert mdb.trainer_presets.find_one({"id": p["id"]})["device_id"] == fx["did"]
        g = requests.get(f"{API}/trainer/game", params=ref(fx)).json()
        assert any(x["id"] == p["id"] for x in g["presets"])
        assert requests.patch(f"{API}/trainer/presets/{p['id']}", json={"name": "  "}).status_code == 400
        assert requests.patch(f"{API}/trainer/presets/TEST_nope", json={"name": "x"}).status_code == 404
        assert requests.delete(f"{API}/trainer/presets/TEST_nope").status_code == 404
    finally:
        assert requests.delete(f"{API}/trainer/presets/{p['id']}").status_code == 200


def test_game_device_pinned(fx):
    g = requests.get(f"{API}/trainer/game", params=ref(fx))
    assert g.status_code == 200 and g.json()["device_id"] == fx["did"]
    ws = requests.get(f"{API}/workshop/games", params={"device_id": fx["did"]})
    assert ws.status_code == 200
