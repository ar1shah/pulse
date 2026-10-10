"""Kiosk exit: pidfile + exit flag handshake with scripts/kiosk.sh, and the local-only endpoint."""
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from pulse import kiosk
from pulse.main import create_app
from pulse.sensors.sim import SimSource


@pytest.fixture
def fake_chromium(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    (tmp_path / "pulse-kiosk.pid").write_text(f"{proc.pid}\n")
    yield proc
    proc.kill()
    proc.wait()


def test_no_pidfile_means_no_kiosk(tmp_path):
    assert not kiosk.running(tmp_path)
    assert kiosk.exit_kiosk(tmp_path) is False
    assert not (tmp_path / "pulse-kiosk.exit").exists()


def test_stale_or_garbage_pidfile_means_no_kiosk(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "pulse-kiosk.pid").write_text(str(dead.pid))
    assert not kiosk.running(tmp_path)
    (tmp_path / "pulse-kiosk.pid").write_text("not a pid")
    assert not kiosk.running(tmp_path)


def test_exit_flags_then_stops_chromium(tmp_path, fake_chromium):
    assert kiosk.running(tmp_path)
    assert kiosk.exit_kiosk(tmp_path) is True
    assert (tmp_path / "pulse-kiosk.exit").exists()       # kiosk.sh sees this and doesn't relaunch
    assert fake_chromium.wait(timeout=5) != 0


def test_endpoints(tmp_path, fake_chromium, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    app = create_app(SimSource("demo", seed=1))
    with TestClient(app) as remote:
        assert remote.get("/api/kiosk").json() == {"running": True}
        assert remote.post("/api/kiosk/exit").status_code == 403     # not from the Pi itself
    assert fake_chromium.poll() is None
    with TestClient(app, client=("127.0.0.1", 50000)) as local:
        assert local.post("/api/kiosk/exit").json() == {"ok": True}
    assert fake_chromium.wait(timeout=5) != 0
