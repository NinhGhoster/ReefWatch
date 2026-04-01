# Spratly Monitor - Daily Cron Setup

## Automated Daily Imagery Check

The `daily_imagery_check.py` script should run daily to:
1. Fetch latest satellite imagery for all 7 Spratly airports
2. Compare with previous day's images
3. Log any changes (could indicate aircraft appearing/disappearing)

## Manual Run
```bash
cd spratly-monitor && python3 daily_imagery_check.py
```

## Cron (Linux)
```bash
# Add to crontab -e
0 12 * * * cd /root/.openclaw/workspace/spratly-monitor && python3 daily_imagery_check.py >> /var/log/spratly-monitor.log 2>&1
```

## OpenClaw Cron (preferred)
Set up via OpenClaw cron to run as a background task daily.

## What to Look For in Results

- `changed: true` means the satellite image differs from the previous capture
- This could mean:
  - Aircraft appeared on runway
  - Aircraft left runway
  - Construction/changes to the island
  - Cloud cover difference
  - Seasonal lighting changes

- Check `imagery_history/` for side-by-side comparison of changed images
- `imagery_log.jsonl` has timestamped records of all checks
