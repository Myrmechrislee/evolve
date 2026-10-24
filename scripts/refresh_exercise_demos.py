"""Refresh the bundled catalogue; media continues to stream from wger on demand.

Run from the project root: python scripts/refresh_exercise_demos.py
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

API = "https://wger.de/api/v2/"
DESTINATION = Path(__file__).resolve().parents[1] / "evolve" / "data" / "exercise_demos.json"


def fetch_pages(resource):
    rows = []
    url = f"{API}{resource}/?limit=1000"
    while url:
        if not url.startswith(API):
            raise ValueError("Unexpected wger pagination URL.")
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        page = response.json()
        rows.extend(page["results"])
        url = page.get("next")
    return rows


def build_catalogue(exercises, licenses):
    license_map = {item["id"]: {"name": item["short_name"], "url": item["url"]} for item in licenses}
    demos = []
    for exercise in exercises:
        translation = next((item for item in exercise["translations"] if item["language"] == 2), None)
        videos = [
            item
            for item in exercise["videos"]
            if urlsplit(item["video"]).scheme == "https"
            and urlsplit(item["video"]).netloc == "wger.de"
            and item["license"] in license_map
        ]
        if not translation or not videos:
            continue
        # Prefer H.264/MP4 for browser compatibility, then the smallest clip.
        video = min(
            videos,
            key=lambda item: (
                item["codec"] != "h264",
                not item["video"].lower().endswith(".mp4"),
                item["size"],
            ),
        )
        demos.append(
            {
                "id": exercise["id"],
                "name": translation["name"],
                "aliases": [item["alias"] for item in translation["aliases"]],
                "source_url": f"{API}exerciseinfo/{exercise['id']}/",
                "name_author": translation["license_author"],
                "name_license": license_map[translation["license"]],
                "video_url": video["video"],
                "video_codec": video["codec"],
                "video_author": video["license_author"],
                "video_license": license_map[video["license"]],
            }
        )
    if not demos:
        raise ValueError("wger returned no video demos; the existing catalogue was kept.")
    return {
        "source": f"{API}exerciseinfo/",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "notes": "Video-backed English entries only. Names and aliases retained; no media modified or bundled.",
        "exercises": demos,
    }


if __name__ == "__main__":
    catalogue = build_catalogue(fetch_pages("exerciseinfo"), fetch_pages("license"))
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(catalogue['exercises'])} exercise demos to {DESTINATION}.")
