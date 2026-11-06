"""Refresh the small, offline Chinese-language region subset of DB-IP Country Lite."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path

import requests

REGIONS = frozenset({"CN", "TW", "HK", "MO", "SG"})
DESTINATION = Path(__file__).resolve().parents[1] / "evolve/data/language_regions.json.gz"


def build_regions(csv_text, month, source_sha256):
    ranges = {4: [], 6: []}
    found = set()
    total = 0
    for row in csv.reader(csv_text):
        total += 1
        start, end, country = row[:3]
        if country not in REGIONS:
            continue
        first, last = ip_address(start), ip_address(end)
        if first.version != last.version or int(first) > int(last):
            raise ValueError("Invalid country IP range")
        ranges[first.version].append([int(first), int(last), country])
        found.add(country)
    if found != REGIONS:
        raise ValueError("Country data is missing a required language region")
    for rows in ranges.values():
        rows.sort()
        for previous, current in zip(rows, rows[1:]):
            if previous[1] >= current[0]:
                raise ValueError("Country IP ranges overlap")
    return {
        "source": f"https://download.db-ip.com/free/dbip-country-lite-{month}.csv.gz",
        "source_sha256": source_sha256, "release": month, "license": "CC-BY-4.0",
        "attribution": "IP Geolocation by DB-IP (https://db-ip.com)",
        "modifications": "Selected CN, TW, HK, MO and SG; converted addresses to sorted integer ranges.",
        "source_records": total, "regions": sorted(REGIONS),
        "ranges": {str(version): rows for version, rows in ranges.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=datetime.now(UTC).strftime("%Y-%m"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        parser.error("Use a release month in YYYY-MM format")
    source = f"https://download.db-ip.com/free/dbip-country-lite-{args.month}.csv.gz"
    response = requests.get(source, timeout=(5, 60))
    response.raise_for_status()
    checksum = hashlib.sha256(response.content).hexdigest()
    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as compressed:
        result = build_regions(io.TextIOWrapper(compressed, encoding="utf-8"), args.month, checksum)
    payload = gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    temporary = DESTINATION.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(DESTINATION)
    print(f"Imported {sum(len(rows) for rows in result['ranges'].values())} region ranges ({len(payload):,} bytes).")


if __name__ == "__main__":
    main()
