"""Server tests: websocket stream, client commands, REST snapshot, static pages."""
import json

import pytest
from fastapi.testclient import TestClient

from pulse.main import create_app
from pulse.sensors.sim import SimSource
from pulse.sources import StubSource, make_source
from pulse.state import validate_snapshot


@pytest.fixture
def client():
    with TestClient(create_app(SimSource("demo", seed=1))) as c:
        yield c


def test_ws_streams_valid_snapshots(client):
    with client.websocket_connect("/ws") as ws:
        seen = [ws.receive_json() for _ in range(5)]
    assert all(validate_snapshot(s) == [] for s in seen)
    assert seen[-1]["t"] > seen[0]["t"]
    assert seen[0]["source"] == "sim"


def test_set_gate_shows_up_in_a_following_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["gate"]["max_range_m"] == 4.0
        ws.send_json({"type": "set_gate", "max_range_m": 2.0, "max_angle_deg": 30})
        gates = [ws.receive_json()["gate"] for _ in range(5)]
    assert gates[-1] == {"max_range_m": 2.0, "max_angle_deg": 30.0}


def test_junk_messages_are_ignored_and_the_stream_continues(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("not json")
        ws.send_text(json.dumps([1, 2, 3]))
        ws.send_json({"type": "nope"})
        ws.send_json({"type": "set_gate", "max_range_m": 99})
        ws.send_json({"type": "set_gate", "max_range_m": "far"})
        gates = [ws.receive_json()["gate"]["max_range_m"] for _ in range(3)]
    assert gates == [4.0, 4.0, 4.0]


def test_a_disconnecting_client_does_not_affect_others(client):
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws") as b:
            b.receive_json()
        # b is gone; a keeps streaming
        first, later = a.receive_json(), None
        for _ in range(4):
            later = a.receive_json()
    assert later["t"] > first["t"]


def test_reset_contacts_message(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset_contacts"})
        snaps = [ws.receive_json() for _ in range(3)]
    assert all(validate_snapshot(s) == [] for s in snaps)


def test_api_snapshot(client):
    d = client.get("/api/snapshot").json()
    assert validate_snapshot(d) == []


def test_api_snapshot_works_before_the_loop_has_ticked():
    c = TestClient(create_app(SimSource("demo", seed=1)))     # no lifespan, no tick yet
    assert validate_snapshot(c.get("/api/snapshot").json()) == []


def test_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/debug").status_code == 200
    assert "WebSocket" in client.get("/debug").text
    assert client.get("/contract.js").status_code == 200
    assert client.get("/").headers["cache-control"] == "no-cache"
    # command.html is a reach goal; 404 until it exists
    assert client.get("/command").status_code in (200, 404)


def test_live_and_replay_are_offline_stubs():
    for name in ("live", "replay"):
        src = make_source(name)
        assert isinstance(src, StubSource) and src.name == name
        with TestClient(create_app(src)) as c:
            d = c.get("/api/snapshot").json()
        assert validate_snapshot(d) == []
        assert d["source"] == name and d["targets"] == []
        assert d["sensors"] == {"ld2450": "offline", "c1001": "offline"}


def test_make_source_env(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "sim")
    assert make_source().name == "sim"
    monkeypatch.setenv("PULSE_SOURCE", "bogus")
    with pytest.raises(ValueError, match="PULSE_SOURCE"):
        make_source()
