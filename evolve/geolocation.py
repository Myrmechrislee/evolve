"""Offline region lookup used only for the initial interface language."""

import gzip
import json
from bisect import bisect_right
from functools import lru_cache
from ipaddress import IPv6Address, ip_address, ip_network
from pathlib import Path

from flask import current_app, request

REGION_DATA = Path(__file__).parent / "data" / "language_regions.json.gz"


@lru_cache(maxsize=1)
def region_ranges():
    try:
        with gzip.open(REGION_DATA, "rt", encoding="utf-8") as source:
            data = json.load(source)
        return {int(version): ([row[0] for row in rows], rows) for version, rows in data["ranges"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        current_app.logger.warning("Language region data unavailable; using browser language preference.")
        return {}


@lru_cache(maxsize=16)
def trusted_networks(setting):
    return tuple(ip_network(value.strip()) for value in setting.split(",") if value.strip())


def parse_address(value):
    try:
        address = ip_address(value)
    except (ValueError, TypeError):
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def visitor_address():
    address = parse_address(request.remote_addr)
    trusted = trusted_networks(current_app.config["LANGUAGE_TRUSTED_PROXIES"])

    def is_trusted(value):
        return value is not None and any(value in network for network in trusted)

    # This changes no Flask request properties, authentication, host or scheme.
    # The first untrusted hop from the right is the visitor, not a spoofed prefix.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if not is_trusted(address) or not forwarded:
        return address
    hops = forwarded.split(",")
    if len(hops) > 20 or len(forwarded) > 2000:
        return None
    for hop in reversed(hops):
        if not is_trusted(address):
            break
        address = parse_address(hop.strip())
        if address is None:
            return None
    return address


def chinese_region(value):
    address = parse_address(value) if isinstance(value, str) else value
    if address is None or not address.is_global:
        return None
    starts, rows = region_ranges().get(address.version, ([], []))
    position = bisect_right(starts, int(address)) - 1
    if position >= 0 and int(address) <= rows[position][1]:
        return rows[position][2]
    return None
