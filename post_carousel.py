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

# Collect slides in order
slides = sorted(glob.glob(f"{POST_DIR}/slide_*.png"))
log(f"Found {len(slides)} slides: {[os.path.basename(s) for s in slides]}")

if not slides:
    tg(f"❌ {SET_LABEL} — No slides found in {POST_DIR}")
    sys.exit(1)

# Step 1: Upload each slide to Facebook (unpublished) → get CDN URL
log("Step 1: Uploading slides to Facebook for CDN URLs...")
cdn_urls = []

for i, slide_path in enumerate(slides, 1):
    log(f"  Uploading slide {i}/{len(slides)}: {os.path.basename(slide_path)}")
    with open(slide_path, "rb") as img:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos",
            data={
                "published": "false",
                "temporary": "true",
                "access_token": PAGE_TOKEN
            },
            files={"source": (os.path.basename(slide_path), img, "image/png")},
            timeout=60
        )
    if r.status_code != 200:
        log(f"  FAILED: {r.text}")
        tg(f"❌ {SET_LABEL} — Failed to upload slide {i}: {r.text[:100]}")
        sys.exit(1)

    photo_id = r.json()["id"]
    log(f"  Photo ID: {photo_id}")

    # Get CDN URL from photo
    r2 = requests.get(
        f"{GRAPH}/{photo_id}",
        params={"fields": "images", "access_token": PAGE_TOKEN}
    )
    images = r2.json().get("images", [])
    if not images:
        log(f"  Could not get CDN URL: {r2.text}")
        tg(f"❌ {SET_LABEL} — No CDN URL for slide {i}")
        sys.exit(1)

    # Use largest image
    cdn_url = max(images, key=lambda x: x.get("width", 0))["source"]
    log(f"  CDN URL: {cdn_url[:60]}...")
    cdn_urls.append(cdn_url)
    time.sleep(1)

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
