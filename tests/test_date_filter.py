import asyncio

import pytest

from brewops.api.main import app
from brewops.db.connection import connect
from brewops.db.queries import get_stats, insert_brew
from brewops.db.schema import init_db

from asgi_client import Response, request


def get(app, path: str) -> Response:
    """Like asgi_client.request, but supports a query string (that helper
    hardcodes query_string=b"" and can't be edited — see tests/ rule)."""
    path, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))

    status = 500
    headers: dict[str, str] = {}
    chunks: list[bytes] = []
    for m in messages:
        if m["type"] == "http.response.start":
            status = m["status"]
            headers = {k.decode(): v.decode() for k, v in m.get("headers", [])}
        elif m["type"] == "http.response.body":
            chunks.append(m.get("body", b""))
    return Response(status, headers, b"".join(chunks))


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "date-filter-test.db")
    init_db(conn)
    insert_brew(conn, 1, "espresso", "2026-06-01 08:00:00", 27.5, 92.0, "csv")
    insert_brew(conn, 1, "espresso", "2026-06-02 09:00:00", 26.0, 91.5, "csv")
    insert_brew(conn, 2, "latte", "2026-06-03 10:00:00", 44.0, 88.0, "csv")
    insert_brew(conn, 3, "lungo", "2026-06-04 11:00:00", 38.0, 90.0, "manual")
    conn.commit()
    yield conn
    conn.close()


def test_get_stats_no_args_is_all_time(conn):
    stats = get_stats(conn)
    assert stats["total_brews"] == 4


def test_get_stats_start_only(conn):
    stats = get_stats(conn, start="2026-06-03 00:00:00")
    assert stats["total_brews"] == 2
    per_day = {d["day"]: d["count"] for d in stats["per_day"]}
    assert per_day == {"2026-06-03": 1, "2026-06-04": 1}


def test_get_stats_end_only(conn):
    stats = get_stats(conn, end="2026-06-03 00:00:00")
    assert stats["total_brews"] == 2
    per_day = {d["day"]: d["count"] for d in stats["per_day"]}
    assert per_day == {"2026-06-01": 1, "2026-06-02": 1}


def test_get_stats_single_day_range_is_inclusive(conn):
    stats = get_stats(conn, start="2026-06-02 00:00:00", end="2026-06-03 00:00:00")
    assert stats["total_brews"] == 1
    assert [d["day"] for d in stats["per_day"]] == ["2026-06-02"]


def test_get_stats_empty_range_zero_fills_per_drink(conn):
    stats = get_stats(conn, start="2020-01-01 00:00:00", end="2020-01-02 00:00:00")
    assert stats["total_brews"] == 0
    per_drink = {d["name"]: d["count"] for d in stats["per_drink"]}
    assert per_drink["espresso"] == 0
    assert per_drink["latte"] == 0
    assert per_drink["cappuccino"] == 0
    assert stats["per_day"] == []


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "date-filter-api-test.db"
    monkeypatch.setenv("BREWOPS_DB", str(path))
    conn = connect(path)
    init_db(conn)
    insert_brew(conn, 1, "espresso", "2026-06-01 08:00:00", 27.5, 92.0, "csv")
    insert_brew(conn, 1, "espresso", "2026-06-02 09:00:00", 26.0, 91.5, "csv")
    insert_brew(conn, 2, "latte", "2026-06-03 10:00:00", 44.0, 88.0, "csv")
    insert_brew(conn, 3, "lungo", "2026-06-04 11:00:00", 38.0, 90.0, "manual")
    conn.commit()
    yield conn
    conn.close()


def test_api_stats_no_args_is_all_time(db):
    r = request(app, "GET", "/api/stats")
    assert r.status == 200
    assert r.json()["total_brews"] == 4


def test_api_stats_with_range(db):
    r = get(app, "/api/stats?start=2026-06-02&end=2026-06-03")
    assert r.status == 200
    stats = r.json()
    assert stats["total_brews"] == 2
    per_day = {d["day"]: d["count"] for d in stats["per_day"]}
    assert per_day == {"2026-06-02": 1, "2026-06-03": 1}


def test_api_stats_single_day_range_is_inclusive(db):
    r = get(app, "/api/stats?start=2026-06-01&end=2026-06-01")
    assert r.status == 200
    stats = r.json()
    assert stats["total_brews"] == 1
    assert [d["day"] for d in stats["per_day"]] == ["2026-06-01"]


def test_api_stats_end_before_start_is_400(db):
    r = get(app, "/api/stats?start=2026-06-04&end=2026-06-01")
    assert r.status == 400
    assert "end date is before start date" in r.json()["detail"]


def test_api_stats_unparsable_date_is_400(db):
    r = get(app, "/api/stats?start=not-a-date")
    assert r.status == 400
    assert "unparsable" in r.json()["detail"]

    r = get(app, "/api/stats?end=also-not-a-date")
    assert r.status == 400
    assert "unparsable" in r.json()["detail"]
