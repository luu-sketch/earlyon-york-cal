# EarlyON Markham + Thornhill calendar feed

An auto-refreshing iCal feed of drop-in and registered programs at:

- **EarlyON Markham Centre** — 3990 14th Avenue, Markham, ON L3R 0B2
- **EarlyON Thornhill Centre** — 7755 Bayview Avenue, Thornhill, ON L3T 4P1

Data source: <https://www.missioninc.com/cso/york/en-ca/earlyon/calendar>

## Subscribe

Once this repo is pushed to GitHub and GitHub Pages is enabled (`Settings → Pages → Branch: main, Folder: /docs`), the feed URL is:

```
https://<your-github-username>.github.io/<repo-name>/earlyon-markham-thornhill.ics
```

### Google Calendar
1. Open Google Calendar → left sidebar → **Other calendars** → **+** → **From URL**.
2. Paste the URL above. Click **Add calendar**.
3. Events appear within a few minutes and re-sync roughly daily.

### Apple Calendar (macOS / iOS)
1. macOS Calendar → **File** → **New Calendar Subscription…** → paste the URL.
2. Set **Auto-refresh** to **Every day**.

## How it refreshes

A GitHub Actions workflow ([`.github/workflows/refresh.yml`](.github/workflows/refresh.yml)) runs every day at 07:00 UTC (~03:00 ET). It re-runs `scrape.py` and commits the updated `.ics` only if events changed. Subscribers see new sessions within a day of Mission Inc publishing them.

You can also trigger a manual refresh from the Actions tab → `refresh-ics` → **Run workflow**.

## Window

The feed contains events from 7 days ago through 8 weeks ahead. Adjust `LOOKBACK_DAYS` / `LOOKAHEAD_DAYS` in `scrape.py` if you want a different range.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scrape.py
open docs/earlyon-markham-thornhill.ics  # preview in Calendar.app
```

Note: `requirements.txt` lists `playwright`, which is only needed by `probe.py` (a one-off diagnostic to confirm API shapes). The production script `scrape.py` only needs `httpx`. If you don't want to install Chromium, you can install just `httpx` and skip the rest.

## How it works

The Mission Inc EarlyON page is an Angular SPA, but its REST backend at `https://www.missioninc.com/OccmsApi/York/eoprogramschedevents` is anonymous. `scrape.py`:

1. Hits `/eoprogramschedevents/lookups` to confirm the two target sites still have the expected codes (`ProvID=EARLY12` Markham, `ProvID=EARLY22` Thornhill). Fails loudly if Mission Inc renames them.
2. Calls `/eoprogramschedevents?Start=…&End=…&HOID=…` once per head office (`EARLY02` and `EARLY03`).
3. Filters to the two `ProvID`s, deduplicates, and emits an RFC 5545 `.ics` with a proper `VTIMEZONE` block for `America/Toronto`. Stable UIDs (sha1 of `ProvID|Id`) mean Google Calendar updates events in place instead of creating duplicates.

## Files

| Path | Purpose |
|---|---|
| `scrape.py` | The generator. Pure `httpx`, no auth needed. |
| `probe.py` | One-off diagnostic; uses Playwright to dump every API response to `tmp_probe/` so you can re-check field names if Mission Inc changes the schema. |
| `docs/earlyon-markham-thornhill.ics` | The generated feed (committed). |
| `.github/workflows/refresh.yml` | Daily cron. |
