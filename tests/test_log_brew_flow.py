"""Real-browser check of the "Log a brew" form, driven with Playwright.

Unlike the other tests (which hit the ASGI app in-process via asgi_client),
this spins up a real uvicorn server against a scratch database and drives it
with an actual browser, so it also catches breakage in app.js/index.html that
in-process API tests can't see.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    db_path = tmp_path / "playwright-test.db"
    port = _free_port()
    env = {**os.environ, "BREWOPS_DB": str(db_path)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "brewops.api.main:app",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        env=env,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base_url}/api/stats", timeout=0.5)
                break
            except (urllib.error.URLError, ConnectionError):
                if proc.poll() is not None:
                    raise RuntimeError("server process exited during startup")
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start in time")
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _total_brews(page) -> int:
    return int(page.locator("#total-brews").inner_text())


def test_log_a_brew_increments_total(live_server, page):
    page.goto(live_server)
    total_before = _total_brews(page)

    page.select_option("#brew-machine", label="Bertha (3rd floor)")
    page.select_option("#brew-drink", label="Espresso")
    page.click("#brew-submit")

    page.wait_for_function(
        "document.getElementById('brew-message').textContent === 'Logged.'"
    )
    assert _total_brews(page) == total_before + 1


def test_log_a_brew_rejects_future_timestamp(live_server, page):
    page.goto(live_server)
    total_before = _total_brews(page)

    page.fill("#brew-timestamp", "2099-01-01T12:00")
    page.click("#brew-submit")

    page.wait_for_function(
        "document.getElementById('brew-message').textContent.includes('future')"
    )
    assert _total_brews(page) == total_before
