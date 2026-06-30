#!/usr/bin/env python3
"""
Scrubbys SG — Instagram carousel auto-poster for GitHub Actions.
Usage: python post_carousel.py posts/setN/
Expects: slide_1.png, slide_2.png, ... slide_N.png + caption.txt in post dir.
"""
import os, sys, glob, requests, time

POST_DIR   = sys.argv[1] if len(sys.argv) > 1 else "posts/set3"
PAGE_TOKEN = os.environ["PAGE_TOKEN"]
PAGE_ID    = os.environ["PAGE_ID"]
IG_ID      = os.environ["IG_USER_ID"]
TG_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT    = os.environ["TELEGRAM_CHAT_ID"]
SET_LABEL  = os.environ.get("SET_LABEL", "Set ?")
GRAPH      = "https://graph.facebook.com/v21.0"

CAP_PATH   = f"{POST_DIR}/caption.txt"

GITHUB_REPO   = os.environ.get("GITHUB_REPOSITORY", "junwei04/scrubbys-autopost")
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

def log(msg):
    print(msg, flush=True)

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": msg}
        )
    except Exception as e:
        log(f"Telegram notify failed: {e}")

with open(CAP_PATH) as f:
    caption = f.read().strip()

CAPTION_MATCH_LEN = 60

def already_posted_on_instagram():
    """Idempotency check — never re-post if a matching caption already exists
    (e.g. this script being re-run by the watchdog after a missed schedule)."""
    r = requests.get(
        f"{GRAPH}/{IG_ID}/media",
        params={"fields": "caption,timestamp", "limit": 10, "access_token": PAGE_TOKEN}
    )
    if r.status_code != 200:
        return False
    needle = caption[:CAPTION_MATCH_LEN]
    for m in r.json().get("data", []):
        if (m.get("caption") or "").startswith(needle):
            return True
    return False

if already_posted_on_instagram():
    log("Already posted on Instagram (matching caption found) — nothing to do.")
    tg(f"ℹ️ {SET_LABEL} — already live on Instagram, watchdog/retry skipped (no duplicate)")
    sys.exit(0)

# Collect slides in order
slides = sorted(glob.glob(f"{POST_DIR}/slide_*.png"))
log(f"Found {len(slides)} slides: {[os.path.basename(s) for s in slides]}")

if not slides:
    tg(f"❌ {SET_LABEL} — No slides found in {POST_DIR}")
    sys.exit(1)

# Step 1: Build public GitHub-raw URLs for each slide directly.
# (Previously relayed each slide through Facebook's /photos endpoint to get
# a CDN URL — removed after discovering Instagram's Reels processing rejects
# FB-relayed video URLs with error 2207076. Same risk applies to images, so
# slides are now hosted directly via GitHub raw URLs instead. Repo must be
# public for these URLs to be fetchable by Instagram.)
log("Step 1: Building GitHub-hosted URLs for slides...")
cdn_urls = []
for i, slide_path in enumerate(slides, 1):
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{slide_path}"
    log(f"  Slide {i}/{len(slides)}: {raw_url}")
    cdn_urls.append(raw_url)

# Step 2: Create IG carousel item containers
log(f"\nStep 2: Creating {len(cdn_urls)} IG carousel item containers...")
item_ids = []

for i, url in enumerate(cdn_urls, 1):
    r = requests.post(
        f"{GRAPH}/{IG_ID}/media",
        data={
            "image_url": url,
            "is_carousel_item": "true",
            "access_token": PAGE_TOKEN
        }
    )
    if r.status_code != 200:
        log(f"  FAILED slide {i}: {r.text}")
        tg(f"❌ {SET_LABEL} — IG carousel item {i} failed: {r.text[:100]}")
        sys.exit(1)

    item_id = r.json()["id"]
    item_ids.append(item_id)
    log(f"  Item {i} container: {item_id}")
    time.sleep(1)

# Step 3: Create carousel album container
log(f"\nStep 3: Creating carousel album container...")
r = requests.post(
    f"{GRAPH}/{IG_ID}/media",
    data={
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "caption": caption,
        "access_token": PAGE_TOKEN
    }
)
if r.status_code != 200:
    log(f"FAILED: {r.text}")
    tg(f"❌ {SET_LABEL} — Carousel album creation failed: {r.text[:100]}")
    sys.exit(1)

album_id = r.json()["id"]
log(f"Album container ID: {album_id}")

# Step 4: Wait for processing
log(f"\nStep 4: Waiting for IG processing...")
for i in range(30):
    time.sleep(5)
    r = requests.get(
        f"{GRAPH}/{album_id}",
        params={"fields": "status_code,status", "access_token": PAGE_TOKEN}
    )
    status = r.json().get("status_code", "unknown")
    log(f"  [{i+1}] {status}")
    if status == "FINISHED":
        break
    if status == "ERROR":
        log(f"Processing error: {r.text}")
        tg(f"❌ {SET_LABEL} — IG carousel processing error")
        sys.exit(1)

# Step 5: Publish
log(f"\nStep 5: Publishing carousel...")
r = requests.post(
    f"{GRAPH}/{IG_ID}/media_publish",
    data={"creation_id": album_id, "access_token": PAGE_TOKEN}
)
log(f"Published: {r.status_code} {r.text}")

if r.status_code == 200:
    log("✅ Carousel published successfully!")
    tg(f"✅ {SET_LABEL} carousel posted to Instagram successfully")
else:
    tg(f"❌ {SET_LABEL} — IG carousel publish failed: {r.text[:100]}")
    sys.exit(1)
