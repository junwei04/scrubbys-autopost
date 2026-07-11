#!/usr/bin/env python3
"""
Scrubbys SG — pre flight validator for posts/setN folders.

Why this exists: Set 7 was built with slide1.png ... slide7.png (no
underscore), but post_carousel.py globs for slide_*.png (with underscore).
The mismatch wasn't caught until the scheduled post silently failed a day
later. This script catches that class of bug at push time instead, by
checking every posts/setN folder against what its own GitHub Actions
workflow actually invokes.

Usage: python validate_posts.py
Exits 1 (and prints every problem found) if any post folder would fail when
its workflow runs. Exits 0 if everything checks out.
"""
import glob, os, re, sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(REPO_DIR, "posts")
WORKFLOWS_DIR = os.path.join(REPO_DIR, ".github", "workflows")

errors = []


def find_script_for_dir(post_dir_name):
    """Reads every workflow yml and returns the post script invoked for this
    posts/<dir>, e.g. 'post_carousel.py' or 'post_instagram.py'. Returns None
    if no workflow references this folder at all (orphaned content)."""
    pattern = re.compile(r"python\s+(post_\w+\.py)\s+posts/" + re.escape(post_dir_name) + r"\b")
    for wf_path in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
        with open(wf_path) as f:
            content = f.read()
        m = pattern.search(content)
        if m:
            return m.group(1), os.path.basename(wf_path)
    return None, None


def validate_carousel(post_dir, post_dir_name):
    slides = sorted(glob.glob(os.path.join(post_dir, "slide_*.png")))
    if not slides:
        # Look for near misses to give an actionable error, not just "0 found"
        near_misses = [f for f in os.listdir(post_dir) if re.match(r"^slide\d+\.png$", f)]
        if near_misses:
            errors.append(
                f"posts/{post_dir_name}: post_carousel.py needs slide_1.png, slide_2.png, ... "
                f"(WITH underscore) but found {sorted(near_misses)} (no underscore). "
                f"Rename to fix."
            )
        else:
            errors.append(
                f"posts/{post_dir_name}: post_carousel.py found 0 files matching slide_*.png. "
                f"This folder would fail to post anything."
            )
    if not os.path.exists(os.path.join(post_dir, "caption.txt")):
        errors.append(f"posts/{post_dir_name}: missing caption.txt")


def validate_reel(post_dir, post_dir_name):
    for required in ("reel.mp4", "thumb.jpg", "caption.txt"):
        if not os.path.exists(os.path.join(post_dir, required)):
            errors.append(f"posts/{post_dir_name}: missing {required}")


VALIDATORS = {
    "post_carousel.py": validate_carousel,
    "post_instagram.py": validate_reel,
}


def main():
    if not os.path.isdir(POSTS_DIR):
        print("No posts/ directory found, nothing to validate.")
        return 0

    for post_dir_name in sorted(os.listdir(POSTS_DIR)):
        post_dir = os.path.join(POSTS_DIR, post_dir_name)
        if not os.path.isdir(post_dir):
            continue

        script, workflow_file = find_script_for_dir(post_dir_name)
        if script is None:
            print(f"posts/{post_dir_name}: no workflow references this folder, skipping "
                  f"(not scheduled, or scheduled via a naming pattern this checker doesn't recognize)")
            continue

        validator = VALIDATORS.get(script)
        if validator is None:
            print(f"posts/{post_dir_name}: uses unrecognized script {script}, skipping")
            continue

        validator(post_dir, post_dir_name)
        print(f"posts/{post_dir_name}: checked against {script} ({workflow_file})")

    if errors:
        print("\nVALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\nAll post folders check out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
