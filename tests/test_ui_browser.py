"""Headless-browser smoke test of the workspace (skipped unless Playwright + Chromium exist).

Serves the app on an in-memory database seeded with a fixture scenario and synthetic
polygons, then drives the three views and asserts there are no console or page errors.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from sqlalchemy.pool import StaticPool

from app.db import create_db_engine, init_db
from app.main import create_app
from tests.test_map_api import seed_with_geometry

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    engine = create_db_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    seed_with_geometry(engine, "reserved_expired")
    port = _free_port()
    config = uvicorn.Config(
        create_app(engine=engine), host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    engine.dispose()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except Exception as exc:  # browser binaries not installed
            pytest.skip(f"Chromium unavailable: {exc}")
        yield chromium
        chromium.close()


def test_workspace_views_render_without_errors(server_url: str, browser) -> None:
    errors: list[str] = []
    page = browser.new_page(viewport={"width": 1366, "height": 860})
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())

    page.goto(f"{server_url}/app#/registry", wait_until="networkidle")
    page.wait_for_selector("table.table tbody tr.clickable", timeout=15000)
    assert "T-000002" in page.inner_text("table.table")
    assert "reservation expired" in page.inner_text("table.table")
    page.click("table.table tbody tr.clickable >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])", timeout=10000)
    assert "Front Range Showers" in page.inner_text("#drawer")
    assert page.is_visible("#drawer button:has-text('Cancel')")
    page.click("#drawer .close")

    page.goto(f"{server_url}/app#/sales", wait_until="networkidle")
    page.fill(".sales-form input.input", "80123, 80127")
    page.click(".sales-form button[type=submit]")
    page.wait_for_selector(".avail-banner", timeout=20000)
    assert "PARTIALLY AVAILABLE" in page.inner_text(".avail-banner").upper()
    assert "Talking points" in page.inner_text("#view")

    page.goto(f"{server_url}/app#/map?zips=80123,80120", wait_until="networkidle")
    page.wait_for_selector(".map-panel", timeout=15000)
    page.wait_for_function("document.querySelector('.metric-row') !== null", timeout=20000)
    panel = page.inner_text(".map-panel")
    assert "Opportunity Units" in panel and "2 selected" in panel
    page.wait_for_function(
        "document.querySelectorAll('.leaflet-interactive').length > 0", timeout=20000
    )
    page.select_option(".map-toolbar select", "tier")
    assert "Tier A" in page.inner_text(".legend")
    # clicking a polygon toggles it in the custom grouping
    before = page.inner_text(".map-panel")
    page.click(".leaflet-interactive >> nth=0")
    page.wait_for_function(
        "(prev) => document.querySelector('.map-panel').innerText !== prev",
        arg=before,
        timeout=10000,
    )
    assert "selected" in page.inner_text(".map-panel")

    tile_errors = [e for e in errors if "openstreetmap" in e.lower() or "net::ERR_FAILED" in e]
    real_errors = [e for e in errors if e not in tile_errors]
    assert real_errors == [], real_errors
    page.close()
