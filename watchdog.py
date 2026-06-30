#!/usr/bin/env python3
"""
Scrubbys SG — posting watchdog. Runs every 15 minutes via watchdog.yml.

Why this exists: GitHub Actions scheduled (cron) triggers are documented as
"best effort" and can be silently DROPPED entirely during high load — not just
delayed. This happened to Set 2 on 2026-06-30: the workflow never ran at all,
with zero trace in the run history, even though it was correctly configured
and showed "active". A single daily cron trigger has no second chance if
GitHub drops it.

This watchdog is the fix: it runs frequently and re-checks every post in
schedule_manifest.json. For each one whose scheduled time (+ grace period)
has passed, it re-runs the post script unconditionally. Since post_instagram.py
and post_carousel.py are now idempotent (they check live platform state before
posting to either platform and skip if already there — see commit f83cffd),
repeatedly invoking them is always safe:
  - If the original per-Set cron fired correctly, this run is a silent no-op.
  - If it was dropped, this run completes the post, at most ~15 min late
    instead of indefinitely missing.

Do not remove the per-Set cron triggers in favour of this watchdog alone —
keep both. They are complementary: the per-Set cron is the primary path when
it works, the watchdog is the safety net when it doesn't.
"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

GRACE_MINUTES = 15      # don't fire until this long after scheduled time
MAX_RETRY_HOURS = 48    # stop auto-retrying after this long, escalate instead

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "schedule_manifest.json")

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]


def tg(msg):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": msg},
        )
    except Exception as e:
        print(f"Telegram notify failed: {e}", flush=True)


def main():
    now = datetime.now(timezone.utc)
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    for entry in manifest:
        scheduled = datetime.fromisoformat(entry["scheduled_utc"]).replace(tzinfo=timezone.utc)
        grace_deadline = scheduled + timedelta(minutes=GRACE_MINUTES)
        max_deadline = scheduled + timedelta(hours=MAX_RETRY_HOURS)

        if now < grace_deadline:
            continue  # not due yet
        if now > max_deadline:
            # Overdue beyond the auto-retry window — escalate once per day rather
            # than spamming every 15 minutes forever.
            if now.hour == scheduled.hour and now.minute < 15:
                tg(f"🚨 {entry['name']} is still not confirmed posted, "
                   f"{MAX_RETRY_HOURS}h past its scheduled time. Watchdog has stopped "
                   f"auto-retrying — needs manual investigation.")
            continue

        print(f"[{now.isoformat()}] {entry['name']} is due (scheduled {entry['scheduled_utc']}, "
              f"grace passed) — running {entry['script']} {entry['dir']}", flush=True)
        result = subprocess.run(
            [sys.executable, entry["script"], entry["dir"]],
            env={**os.environ, "SET_LABEL": entry["name"]},
            capture_output=True, text=True,
        )
        print(result.stdout, flush=True)
        if result.returncode != 0:
            print(result.stderr, flush=True)


if __name__ == "__main__":
    main()
