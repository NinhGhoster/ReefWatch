# ReefWatch Cron Setup

## Goal

Run a lightweight daily ReefWatch refresh that keeps the app-facing `derived/` snapshot current without assuming paid APIs or committed secrets.

Recommended daily workflow:
1. refresh free imagery / traffic sources as available
2. refresh optional Planet thumbnails only when `PLANET_API_KEY` is configured locally
3. export the normalized MVP snapshot
4. validate the derived contract before any downstream report/UI step

## Manual Run

```bash
cd /root/.openclaw/workspace/apps/ReefWatch
python3 scripts/daily_imagery_check.py
python3 scripts/export_mvp_snapshot.py
python3 scripts/validate_mvp_snapshot.py
```

If Planet is configured locally and you want an explicit thumbnail pass for priority features first:

```bash
cd /root/.openclaw/workspace/apps/ReefWatch
python3 scripts/planet_fetch.py --config-check
python3 scripts/planet_fetch.py --feature fiery_cross_reef --days 14 --resume
python3 scripts/export_mvp_snapshot.py
python3 scripts/validate_mvp_snapshot.py
```

## Cron (Linux)

```bash
# Add to crontab -e
15 2 * * * cd /root/.openclaw/workspace/apps/ReefWatch && python3 scripts/daily_imagery_check.py && python3 scripts/export_mvp_snapshot.py && python3 scripts/validate_mvp_snapshot.py >> /var/log/reefwatch.log 2>&1
```

## OpenClaw Cron (preferred)

Use an isolated `agentTurn` job that runs the same sequence and reports only a concise summary.

Suggested prompt shape:
- run the daily imagery / monitoring refresh
- run `python3 scripts/export_mvp_snapshot.py`
- run `python3 scripts/validate_mvp_snapshot.py`
- report changed counts, pending review count, and any source-health problems
- do not print or store secret values

## What to Check in Results

- `derived/overview.json` for the daily-brief view
- `derived/feature_status.jsonl` for feature list / triage state
- `derived/review_queue.json` for pending change review items
- `derived/source_health.json` for secret-safe config and ingest status

## Operational Notes

- ReefWatch is now feature-centric, not airport-only.
- The normalized export layer covers all 77 monitored Spratly + Paracel features.
- Planet should stay optional: no cron should fail just because `PLANET_API_KEY` is absent.
- Auth/config checks must remain secret-safe; only report whether config is present, never the key itself.
