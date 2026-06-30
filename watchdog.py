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
and post_carousel.py are idempotent (they check live platform state before
posting to either platform and skip if already there — see commit f83cffd),
repeatedly invoking them is always safe:
  - If the original per-Set cron fired correctly, this run is a silent no-op.
  - If it was dropped, this run completes the post, at most ~15 min late
    instead of indefinitely missing.

This script deliberately does NOT write back to the repo (no auto-commit/push)
— that's a meaningfully bigger capability than "retry a post" and wasn't
separately authorized. Confirmed-posted entries are skipped SILENTLY (console
log only, no Telegram message, no manifest mutation) every run rather than
pruned, so re-checking a long-done entry stays cheap and never spams or false-
alarms. schedule_manifest.json should be manually trimmed of old completed
entries periodically as routine maintenance — not automated.

Do not remove the per-Set cron triggers in favour of this watchdog alone —
keep both. They are complementary: the per-Set cron is the primary path when
it works, the watchdog is the safety net when it doesn't.
"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

GRACE_MINUTES = 15      # don't fire until this long after scheduled time
MAX_RETRY_HOURS = 48    # stop auto-retrying after this long, escalate instead

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(REPO_DIR, "schedule_manifest.json")

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


def is_already_posted(entry):
    """Checks Instagram for a matching-caption post. Used to decide whether to
    skip silently (already done) before attempting anything, so the watchdog
    never sends a false 'still not posted' alarm for something that actually
    succeeded, and never re-runs a post script unnecessarily."""
    import requests
    with open(os.path.join(REPO_DIR, entry["dir"], "caption.txt")) as f:
        caption = f.read().strip()
    needle = caption[:60]
    ig_id = os.environ["IG_USER_ID"]
    page_token = os.environ["PAGE_TOKEN"]
    r = requests.get(
        f"https://graph.facebook.com/v21.0/{ig_id}/media",
        params={"fields": "caption,timestamp", "limit": 15, "access_token": page_token},
    )
    if r.status_code != 200:
        return False
    return any((m.get("caption") or "").startswith(needle) for m in r.json().get("data", []))


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

        if is_already_posted(entry):
            print(f"{entry['name']}: already posted, skipping silently.", flush=True)
            continue

        if now > max_deadline:
            # Escalate at most once per day (only in the first 15-min tick of
            # the scheduled hour) rather than every run.
            if now.hour == scheduled.hour and now.minute < 15:
                tg(f"🚨 {entry['name']} is still not posted, {MAX_RETRY_HOURS}h past its "
                   f"scheduled time. Watchdog has stopped auto-retrying — needs manual "
                   f"investigation.")
            continue

        print(f"[{now.isoformat()}] {entry['name']} is due and not yet posted — "
              f"running {entry['script']} {entry['dir']}", flush=True)
        result = subprocess.run(
            [sys.executable, entry["script"], entry["dir"]],
            cwd=REPO_DIR,
            env={**os.environ, "SET_LABEL": entry["name"]},
            capture_output=True, text=True,
        )
        print(result.stdout, flush=True)
        if result.returncode != 0:
            print(result.stderr, flush=True)


if __name__ == "__main__":
    main()
