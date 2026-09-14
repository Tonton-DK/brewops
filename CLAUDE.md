# BrewOps

Telemetry app for the office coffee machines. Python with FastAPI, data in SQLite.

## Architecture

One-way pipeline, all in `src/brewops/`: **ingest → db → api → frontend**.

- `ingest/loader.py`, `ingest/cli.py` — parses CSV files into `brew_events` / `maintenance_events` rows.
- `db/schema.py`, `db/connection.py`, `db/queries.py` — SQLite schema, connection helper, and all reads/writes. No ORM: raw `sqlite3` with `row_factory = sqlite3.Row`.
- `api/main.py` — single FastAPI app that serves the JSON API under `/api/*` and mounts the static frontend at `/`, both on one process/port (8123).
- `frontend/` — plain `index.html` + `app.js` + `style.css`. No template engine, no build step, no framework; `app.js` fetches JSON client-side and renders it into the DOM.

Machine/drink "health" and stats (`get_machine_health`, `get_stats` in `queries.py`) are always derived at query time from `brew_events`/`maintenance_events` — there's no stored aggregate or health table.

## Ingestion paths

Two ways data gets into `brew_events`, distinguished by the `source` column (`'csv'` or `'manual'`):

1. **CSV batch ingest** — `uv run ingest [path]` (default `data/inbox`) reads `brews_*.csv` (source=`csv`), `manual_*.csv` (source=`manual`, exports of the paper log kept by hand-logged machines), and `maintenance_*.csv`. Bad rows are skipped and reported; the rest of the file still loads. See `ingest/loader.py` for column formats.
2. **Manual entry** — the frontend's "Log a brew" / "Log maintenance" forms POST to `/api/brews` / `/api/maintenance`, which always insert with `source='manual'`.

## Run and test

```
uv run start          # serve app at http://localhost:8123
uv run seed           # wipe the db and re-ingest data/inbox from scratch
uv run ingest [path]  # ingest a CSV file/folder without resetting the db
uv run pytest         # run the test suite (tests/test_db.py, test_api.py, test_ingest.py, test_frontend.py)
```

DB file path defaults to `./brewops.db`, overridable via `BREWOPS_DB`.

## Conventions

- Timestamps are naive local time, stored as `'YYYY-MM-DD HH:MM:SS'` text; parsing (`parse_timestamp` in `api/main.py`, `_parse_timestamp` in `ingest/loader.py`) rejects future timestamps.
- `drink_types` (seeded from `DRINK_TYPES` in `schema.py`) is the single source of truth for valid drinks; `brew_events.drink_type` is a FK on the `name` key, not an id. Adding a drink means editing that list and reseeding — see the `add-drink-type` skill.
- API endpoints return raw dicts from `queries.py` functions directly (no Pydantic response models); request bodies do use Pydantic models (`BrewIn`, `MaintenanceIn`).
- Tests are fixed acceptance criteria: extend implementation code to satisfy existing tests rather than editing test files.
