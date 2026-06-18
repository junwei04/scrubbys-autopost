#!/usr/bin/env python3
"""
Scrubbys SG — Instagram auto-poster for GitHub Actions.
Usage: python post_instagram.py posts/setN/
"""
import os, sys, json, requests, time

POST_DIR   = sys.argv[1] if len(sys.argv) > 1 else "posts/set1"
PAGE_TOKEN = os.environ["PAGE_TOKEN"]
PAGE_ID    = os.environ["PAGE_ID"]
IG_ID      = os.environ["IG_USER_ID"]
TG_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT    = os.environ["TELEGRAM_CHAT_ID"]
SET_LABEL  = os.environ.get("SET_LABEL", "Set ?")

REEL_PATH  = f"{POST_DIR}/reel.mp4"
THUMB_PATH = f"{POST_DIR}/thumb.jpg"
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

# Step 1: Upload video to Facebook to get a fresh CDN URL
log("Step 1: Uploading to Facebook for CDN URL...")
with open(REEL_PATH, "rb") as vid, open(THUMB_PATH, "rb") as thumb:
    r = requests.post(
        f"https://graph.facebook.com/v21.0/{PAGE_ID}/videos",
        data={"published": "true", "access_token": PAGE_TOKEN},
        files={"source": ("reel.mp4", vid, "video/mp4"),
               "thumb":  ("thumb.jpg", thumb, "image/jpeg")},
        timeout=180
    )

if r.status_code != 200:
    log(f"FB upload failed: {r.text}")
    tg(f"❌ {SET_LABEL} — Facebook upload failed")
    sys.exit(1)

fb_video_id = r.json()["id"]
log(f"FB Video ID: {fb_video_id}")

time.sleep(15)

r = requests.get(
    f"https://graph.facebook.com/v21.0/{fb_video_id}",
    params={"fields": "source", "access_token": PAGE_TOKEN}
)
video_url = r.json().get("source")
log(f"CDN URL obtained: {video_url[:60]}...")

# Step 2: Create IG Reel container
log("Step 2: Creating IG Reel container...")
r = requests.post(
    f"https://graph.facebook.com/v21.0/{IG_ID}/media",
    data={"media_type": "REELS", "video_url": video_url,
          "caption": caption, "access_token": PAGE_TOKEN}
)
log(f"Container response: {r.status_code} {r.text[:200]}")
if r.status_code != 200:
    tg(f"❌ {SET_LABEL} — IG container creation failed")
    sys.exit(1)

container_id = r.json()["id"]
log(f"Container ID: {container_id}")

# Step 3: Wait for processing
log("Step 3: Waiting for IG processing...")
for i in range(40):
    time.sleep(10)
    r = requests.get(
        f"https://graph.facebook.com/v21.0/{container_id}",
        params={"fields": "status_code,status", "access_token": PAGE_TOKEN}
    )
    status = r.json().get("status_code", "unknown")
    log(f"  [{i+1}] {status}")
    if status == "FINISHED":
        break
    if status == "ERROR":
        log(f"Error: {r.text}")
        tg(f"❌ {SET_LABEL} — IG processing error")
        sys.exit(1)

# Step 4: Publish
log("Step 4: Publishing IG Reel...")
r = requests.post(
    f"https://graph.facebook.com/v21.0/{IG_ID}/media_publish",
    data={"creation_id": container_id, "access_token": PAGE_TOKEN}
)
log(f"Published: {r.status_code} {r.text}")

if r.status_code == 200:
    tg(f"✅ {SET_LABEL} posted to Instagram successfully")
else:
    tg(f"❌ {SET_LABEL} — IG publish failed: {r.text[:100]}")
    sys.exit(1)
