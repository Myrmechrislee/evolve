"""Import Free Exercise DB instructions and small, locally served form photos.

Run: python scripts/refresh_exercise_hints.py [--archive /path/to/source.tar.gz]
Requires requirements-dev.txt. The app itself needs no image-processing library.
"""

import argparse
import hashlib
import io
import json
import re
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import requests
from PIL import Image, ImageOps

SOURCE = "https://github.com/yuhonas/free-exercise-db"
REVISION = "f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5"
ROOT = Path(__file__).resolve().parents[1]
LICENSE = {"name": "The Unlicense", "url": f"{SOURCE}/blob/{REVISION}/LICENSE.md"}


def build_catalogue(exercises, revision=REVISION):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use a full source commit SHA for a reproducible import.")
    hints = []
    seen = set()
    for exercise in exercises:
        identifier = exercise["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or identifier in seen:
            raise ValueError("Invalid or duplicate exercise ID; the existing catalogue was kept.")
        seen.add(identifier)
        instructions = [step.strip() for step in exercise["instructions"] if step.strip()]
        images = exercise["images"]
        if not instructions or not images:
            continue
        if any(not re.fullmatch(rf"{re.escape(identifier)}/[0-9]+\.jpg", path) for path in images):
            raise ValueError("Unexpected image path; the existing catalogue was kept.")
        hints.append({
            "id": identifier,
            "name": exercise["name"],
            "instructions": instructions,
            "images": images,
            "primary_muscles": exercise["primaryMuscles"],
            "secondary_muscles": exercise["secondaryMuscles"],
            "equipment": exercise["equipment"],
            "level": exercise["level"],
            "category": exercise["category"],
            "source_url": f"{SOURCE}/blob/{revision}/exercises/{identifier}.json",
        })
    if not hints:
        raise ValueError("No complete exercise hints; the existing catalogue was kept.")
    return {
        "source": SOURCE,
        "revision": revision,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "license": {**LICENSE, "url": f"{SOURCE}/blob/{revision}/LICENSE.md"},
        "notes": "Entries with photos and instructions only. Text retained; photos resized to 480px WebP.",
        "exercises": hints,
    }


def import_archive(archive_path, root=ROOT, revision=REVISION):
    with tarfile.open(archive_path, "r:gz") as archive, tempfile.TemporaryDirectory() as staging:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        data_paths = [path for path in members if path.endswith("/dist/exercises.json")]
        if len(data_paths) != 1:
            raise ValueError("Expected one Free Exercise DB dataset.")
        prefix = data_paths[0].removesuffix("dist/exercises.json")
        catalogue = build_catalogue(json.load(archive.extractfile(members[data_paths[0]])), revision)
        stage = Path(staging)
        for hint in catalogue["exercises"]:
            local_images = []
            for path in hint["images"]:
                member = members[f"{prefix}exercises/{path}"]
                with Image.open(archive.extractfile(member)) as original:
                    photo = ImageOps.exif_transpose(original).convert("RGB")
                    photo.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    photo.save(output, format="WEBP", quality=75, method=6)
                content = output.getvalue()
                filename = f"{hashlib.sha256(content).hexdigest()[:24]}.webp"
                (stage / filename).write_bytes(content)
                local_images.append(f"/static/exercise-images/{filename}")
            hint["images"] = local_images
        # Validate and encode everything before publishing. A failed import leaves
        # the old catalogue and its photos usable; unused photos are harmless.
        license_text = archive.extractfile(members[f"{prefix}LICENSE.md"]).read()
        encoded = json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n"
        destination = root / "evolve/data/exercise_hints.json"
        images = root / "evolve/static/exercise-images"
        images.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        for photo in stage.iterdir():
            target = images / photo.name
            if not target.exists():
                pending_photo = target.with_suffix(".tmp")
                pending_photo.write_bytes(photo.read_bytes())
                pending_photo.replace(target)
        (destination.parent / "free-exercise-db-LICENSE.txt").write_bytes(license_text)
        pending = destination.with_suffix(".tmp")
        pending.write_text(encoded, encoding="utf-8")
        pending.replace(destination)
        return catalogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded source tarball.")
    parser.add_argument("--revision", default=REVISION, help="Full source commit SHA (defaults to pinned version).")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full source commit SHA")
    with tempfile.TemporaryDirectory() as download:
        archive_path = args.archive or Path(download) / "source.tar.gz"
        if not args.archive:
            url = f"https://api.github.com/repos/yuhonas/free-exercise-db/tarball/{args.revision}"
            with requests.get(url, stream=True, timeout=(15, 180)) as response:
                response.raise_for_status()
                with archive_path.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
        catalogue = import_archive(archive_path, revision=args.revision)
    print(f"Imported {len(catalogue['exercises'])} exercise hints and their local photos.")


if __name__ == "__main__":
    main()
