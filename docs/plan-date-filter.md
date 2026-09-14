# Plan: Dashboard date-range filter (ticket 005)

Implements `tickets/005-date-filter.md`: let the dashboard be filtered to a
date range, with the stat tiles, per-drink bars, and timeline chart all
following the selected range. Machine cards are explicitly OUT OF SCOPE for
this pass (see "Out of scope" below) — do not touch `get_machine_health` or
`/api/machines/{id}`.

Read `CLAUDE.md` at the repo root first — it describes the overall
architecture (`ingest → db → api → frontend`) and conventions (naive local
timestamps stored as `'YYYY-MM-DD HH:MM:SS'` text, no ORM, endpoints return
raw dicts).

**Rule: do not edit anything under `tests/`.** Those files are fixed
acceptance criteria. If you think a test would need to change to make this
work, stop and flag it instead of editing the test. All existing tests in
`tests/test_db.py` and `tests/test_api.py` call `get_stats(conn)` and
`GET /api/stats` with no date args — your changes must keep that no-args
form working exactly as it does today (all-time totals), so those tests
keep passing unmodified.

## 1. `src/brewops/db/queries.py` — `get_stats`

Current signature (line 68):

```python
def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
```

Change to:

```python
def get_stats(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
```

- `start` and `end` are storage-format timestamp strings
  (`'YYYY-MM-DD HH:MM:SS'`), or `None`.
- Range is **half-open and inclusive of both boundary dates**: a brew counts
  if `timestamp >= start` (when `start` is given) and `timestamp < end`
  (when `end` is given). Callers are responsible for turning a user-picked
  end *date* into an end-of-day-exclusive timestamp (see section 3) — this
  function just applies whatever strings it's given as `>=` / `<`.
- Build the WHERE clause dynamically so any combination of
  `start`/`end`/neither/both works:

```python
clauses = []
params: list[str] = []
if start is not None:
    clauses.append("timestamp >= ?")
    params.append(start)
if end is not None:
    clauses.append("timestamp < ?")
    params.append(end)
where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
```

- `total`: add `where` (with `params`) to the existing
  `SELECT COUNT(*) AS n FROM brew_events`.
- `per_drink`: **do not put the date filter in a bare `WHERE` after the
  `LEFT JOIN`** — that turns it into an inner join and drinks with zero
  brews in range would silently disappear from the result (the existing
  test `per_drink["cappuccino"] == 0` depends on zero-count rows still
  appearing). Put the date condition in the `ON` clause instead:

```python
SELECT dt.name, dt.label, COUNT(be.id) AS count
FROM drink_types dt
LEFT JOIN brew_events be
  ON be.drink_type = dt.name
  {AND-ed date conditions using be.timestamp go here}
GROUP BY dt.id
ORDER BY dt.id
```

  i.e. append `AND be.timestamp >= ?` / `AND be.timestamp < ?` onto the `ON`
  clause when `start`/`end` are set, not a separate `WHERE`.
- `per_day`: add the same `where`/`params` (using plain `WHERE`, this one
  has no join) to the existing `GROUP BY DATE(timestamp)` query.
- Return shape (`total_brews`, `per_drink`, `per_day`) is unchanged.

## 2. `src/brewops/api/main.py` — `/api/stats`

Current handler (line 74):

```python
@app.get("/api/stats")
def stats(conn: sqlite3.Connection = Depends(get_db)):
    return queries.get_stats(conn)
```

Add two optional query parameters, `start` and `end`, as **plain calendar
dates** (`YYYY-MM-DD`) — that's what a `<input type="date">` control
produces, and it matches the existing daily granularity of `per_day`. Do
**not** reuse `parse_timestamp` as-is (it requires a full datetime and
rejects future timestamps, which a date-only filter shouldn't need to
reject — a user should be able to pick a range that extends to "today").

```python
from datetime import date, datetime

def parse_filter_date(value: str, param_name: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"unparsable {param_name} {value!r}")

@app.get("/api/stats")
def stats(
    start: str | None = None,
    end: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    start_ts = None
    end_ts = None
    if start is not None:
        start_ts = parse_filter_date(start, "start").strftime("%Y-%m-%d 00:00:00")
    if end is not None:
        end_date = parse_filter_date(end, "end")
        if start is not None and end_date < datetime.strptime(start, "%Y-%m-%d").date():
            raise HTTPException(400, "end date is before start date")
        end_ts = end_date.strftime("%Y-%m-%d 00:00:00")
        # end is exclusive lower-bound-of-next-day, i.e. push it one day forward
        # so that the whole end date is included:
        from datetime import timedelta
        end_ts = (end_date + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    return queries.get_stats(conn, start=start_ts, end=end_ts)
```

(Feel free to tidy the imports/placement above — the point is: parse
`start`/`end` as dates, convert `end` to the start of the *next* day before
passing to `get_stats` so the picked end date is fully included, reject
`end < start` with a 400, and leave both params optional so
`GET /api/stats` with no query string behaves exactly as before.)

Do not add `start`/`end` to `/api/machines/{id}` — out of scope, see below.

## 3. Frontend controls

### `src/brewops/frontend/index.html`

Inside the `#dashboard` section (around line 17-31, before or above
`.stat-tiles`), add a small filter bar:

```html
<div class="panel date-filter">
  <label for="filter-start">From</label>
  <input type="date" id="filter-start">
  <label for="filter-end">To</label>
  <input type="date" id="filter-end">
  <button type="button" id="filter-apply">Apply</button>
  <button type="button" id="filter-clear">Clear</button>
  <p id="filter-message" class="message" role="status"></p>
</div>
```

Placement and exact classes are flexible — match the existing `.panel`
style used elsewhere in this file so it looks consistent; no new CSS
framework, this project has no build step (see `CLAUDE.md`).

### `src/brewops/frontend/app.js`

- Add module-level (or closured) state for the current filter, e.g.:

```js
function getDateFilter() {
  const start = document.getElementById("filter-start").value; // "" if unset
  const end = document.getElementById("filter-end").value;
  return { start: start || null, end: end || null };
}
```

- Change `loadDashboard()` (line 80) to build the query string from
  `getDateFilter()` and pass it to `/api/stats`:

```js
async function loadDashboard() {
  const { start, end } = getDateFilter();
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  const stats = await fetchJSON(`/api/stats${qs ? "?" + qs : ""}`);
  ...
```

  The rest of `loadDashboard` (tiles, `renderDrinkBars`, `renderTimeline`,
  machine cards) stays as-is — machine cards are not filtered (see "Out of
  scope").

- Wire `#filter-apply` to call `loadDashboard()` again, and validate
  client-side before firing the request (see edge cases below) using
  `#filter-message` the same way `submitForm` uses `#brew-message` /
  `#maintenance-message` for errors.
- Wire `#filter-clear` to blank both date inputs and call `loadDashboard()`
  to go back to all-time.
- The `brews-today` tile (`index.html` line 24, `"brews on last active
  day"`) currently shows the count for the *last* day in `stats.per_day`.
  Once a range is applied, that's "last day in the filtered range," not
  necessarily today — rename the label in `index.html` to something
  range-neutral, e.g. `"brews on last day shown"`, so it isn't misleading.
  Don't change the underlying logic in `app.js` (`lastDay =
  stats.per_day[stats.per_day.length - 1]`), just the label text.

## 4. Edge cases

- **No filter set (both inputs empty):** must behave exactly like today —
  `GET /api/stats` with no query params, all-time totals. This is what the
  existing tests exercise; don't break it.
- **Only `start` given:** everything from `start` onward, open-ended.
- **Only `end` given:** everything up to and including `end`'s date,
  open-started.
- **`start` after `end`:** reject before hitting the network. Do the check
  client-side in the `#filter-apply` handler (compare the two `<input
  type="date">` string values, which sort correctly as ISO strings) and
  show an error in `#filter-message` instead of calling `loadDashboard()`.
  Also keep the server-side check in `main.py` (the `end_date < start_date`
  branch above) as a second line of defense — a 400 with a clear
  `detail` message, not a 500.
- **Empty range (valid dates, but zero brews fall inside them):** `get_stats`
  must return `total_brews: 0`, `per_drink` with every drink at `count: 0`
  (this is exactly what the existing `LEFT JOIN ... ON` fix in section 1
  guarantees), and `per_day: []`. On the frontend, confirm
  `renderDrinkBars` and `renderTimeline` don't throw on an empty `per_day`
  array — `renderTimeline` (app.js line 29) already returns early when
  `perDay.length === 0`, so the SVG just stays empty; the `brews-today`
  tile's `lastDay` will be `undefined` and the existing `lastDay ? ... : 0`
  guard (app.js line 84) already handles that by showing `0`. No new guard
  code needed there, just verify it.
- **Days with no brews inside a *non-empty* range:** `per_day` only
  contains rows for days that have at least one brew (it's a `GROUP BY
  DATE(timestamp)` with no zero-fill). This is pre-existing behavior — the
  timeline chart already renders gaps as skipped bars, not zero-height
  bars. Do not attempt to zero-fill missing days; that's a bigger change
  than this ticket asks for and no test expects it.
- **Single-day range (`start == end`):** must include that whole day. This
  is why `end` gets pushed forward one day server-side before being passed
  to `get_stats` as an exclusive upper bound — verify a range where `start`
  and `end` are the same date returns brews from that date.
- **Malformed date string reaching the API directly** (e.g. someone hits
  `/api/stats?start=not-a-date` outside the UI): must return `400` with a
  message containing `"unparsable"`, not a 500 — this is what
  `parse_filter_date` above is for.

## 5. Out of scope (confirm with user if unsure, don't silently expand)

- Machine health cards (`get_machine_health`, `/api/machines/{id}`,
  `renderMachineCards`) are **not** filtered by date in this pass. The
  ticket text ("the dashboard shows everything... let people pick a date
  range and have the numbers and charts follow") is about the top
  stats/charts section; machine cards are a separate zone. Do not add
  `start`/`end` params to `get_machine_health` or the `/api/machines/{id}`
  route.
- No persistence of the chosen range (URL query params, localStorage) —
  it resets on page reload. Not asked for.
- No date-range validation against "future dates" — unlike
  `parse_timestamp` (used for logging new brews), the filter's `end` date
  is allowed to be today or in the future; it just won't match any rows.

## 6. How to verify

Run from the repo root:

```
uv run pytest
```

All existing tests in `tests/test_db.py` and `tests/test_api.py` must
still pass unmodified — they call `get_stats`/`GET /api/stats` with no
date args, so this is the main regression check for section 1 and 2.

Manual/UI check (per `CLAUDE.md`'s "test the golden path in a browser"
guidance — use the `run` skill or `uv run start` directly, then open
`http://localhost:8123`):

1. `uv run seed` to get a known dataset, then `uv run start`.
2. Load the dashboard with no filter set — confirm tiles/bars/timeline
   match what you see before this change (sanity check for regressions).
3. Set a `From`/`To` range that covers a known subset of `data/inbox`'s
   dates, click Apply — confirm `total_brews`, the per-drink bars, and the
   timeline chart all shrink to just that range.
4. Set `From` after `To`, click Apply — confirm you get an inline error in
   `#filter-message` and no request errors in the browser console (or, if
   you skip the client-side check and let it hit the server, confirm a
   clean 400 with a readable message, not a stack trace).
5. Pick a range with no brews in it — confirm the tiles show `0`, the bars
   all show zero-width/zero counts (not blank/broken), and the timeline SVG
   is empty but the page doesn't error.
6. Click Clear — confirm it returns to the all-time view.
7. Confirm machine cards below the chart are unaffected by the filter
   (still showing all-time brew counts) — this is expected per the "Out of
   scope" section, not a bug.

Also worth an explicit new automated test (add to `tests/`? — **no**, per
the no-edit-tests rule above, do not add to the existing test files either
without checking with the user first; if you want automated coverage for
this feature, ask the user whether a new test file is acceptable, since
"don't modify tests/" has historically been interpreted strictly in this
repo).
