
"""
AYCF Radar integration for FlyHopGo.

Adds airport country information to radar responses.

Register in app.py:

from aycf_radar import radar_bp
app.register_blueprint(radar_bp)
"""

import time
import threading
import logging
import re
import unicodedata

import requests
import airportsdata
import pycountry

from functools import lru_cache
from collections import defaultdict
from flask import Blueprint, jsonify, request

radar_bp = Blueprint("radar", __name__)

BASE = "https://aycfradar.com/api"

CACHE = {}
LOCK = threading.Lock()

TTL = {
    "status": 120,
    "graph": 600,
    "flights": 90,
    "connections": 90
}

logger = logging.getLogger(__name__)


# --------------------------------------------------
# AIRPORT AND COUNTRY DATABASE
# --------------------------------------------------

def normalize(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value or "")
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip().casefold()


def country_name(code):
    special = {
        "XK": "Kosovo",
        "GB": "United Kingdom",
        "CZ": "Czech Republic",
        "TR": "Turkey",
        "MD": "Moldova",
        "MK": "North Macedonia"
    }

    code = str(code or "").upper()

    if code in special:
        return special[code]

    country = pycountry.countries.get(
        alpha_2=code
    )

    return country.name if country else ""


@lru_cache(maxsize=1)
def airport_database():
    airports = airportsdata.load("IATA")

    by_city = defaultdict(set)
    by_name = defaultdict(set)

    for code, airport in airports.items():
        country = country_name(
            airport.get("country")
        )

        if not country:
            continue

        city = normalize(
            airport.get("city")
        )

        name = normalize(
            airport.get("name")
        )

        if city:
            by_city[city].add(country)

        if name:
            by_name[name].add(country)

    return airports, by_city, by_name


# Specific city names used in flight data.
# These are exact matches, not broad guesses.

CITY_ALIASES = {
    "asturias": "Spain",
    "asturien": "Spain",
    "oviedo": "Spain",
    "pristina": "Kosovo",
    "prishtina": "Kosovo",
    "ohrid": "North Macedonia",
    "kutaisi": "Georgia",
    "chisinau": "Moldova",
    "chisinau airport": "Moldova"
}


def airport_country(value):
    text = str(value or "").strip()

    if not text:
        return ""

    airports, by_city, by_name = airport_database()

    # Explicit IATA code
    match = re.search(
        r"\(([A-Z]{3})\)",
        text,
        re.IGNORECASE
    )

    if match:
        code = match.group(1).upper()

    elif re.fullmatch(
        r"[A-Z]{3}",
        text,
        re.IGNORECASE
    ):
        code = text.upper()

    else:
        code = ""

    if code and code in airports:
        return country_name(
            airports[code].get("country")
        )

    normalized = normalize(text)

    if normalized in CITY_ALIASES:
        return CITY_ALIASES[normalized]

    countries = by_city.get(
        normalized,
        set()
    )

    if len(countries) == 1:
        return next(iter(countries))

    countries = by_name.get(
        normalized,
        set()
    )

    if len(countries) == 1:
        return next(iter(countries))

    # Avoid assigning countries to ambiguous cities.
    return ""


def add_country_to_record(record):
    if not isinstance(record, dict):
        return record

    updated = dict(record)

    city = (
        updated.get("city")
        or updated.get("name")
        or updated.get("airport")
        or updated.get("iata")
        or updated.get("code")
    )

    if city and not updated.get("country"):
        country = airport_country(city)

        if country:
            updated["country"] = country

    return updated


def enrich_graph(payload):
    result = dict(payload)

    nodes = result.get("nodes")

    if isinstance(nodes, list):
        result["nodes"] = [
            add_country_to_record(node)
            for node in nodes
        ]

    return result


def enrich_connections(payload):
    result = dict(payload)

    connections = result.get("connections")

    if not isinstance(connections, list):
        return result

    enriched = []

    for connection in connections:
        if not isinstance(connection, dict):
            enriched.append(connection)
            continue

        item = dict(connection)

        # Country information for intermediate cities.
        via = item.get("via")

        if isinstance(via, list):
            item["viaCountries"] = [
                airport_country(city)
                for city in via
            ]

        legs = item.get("legs")

        if isinstance(legs, list):
            new_legs = []

            for leg in legs:
                if not isinstance(leg, dict):
                    new_legs.append(leg)
                    continue

                new_leg = dict(leg)

                new_leg["fromCountry"] = (
                    airport_country(
                        leg.get("from")
                    )
                )

                new_leg["toCountry"] = (
                    airport_country(
                        leg.get("to")
                    )
                )

                new_legs.append(new_leg)

            item["legs"] = new_legs

        enriched.append(item)

    result["connections"] = enriched

    return result


# --------------------------------------------------
# RADAR API CACHE
# --------------------------------------------------

def radar_get(endpoint, params=None):
    params = params or {}

    cache_key = (
        endpoint,
        tuple(sorted(params.items()))
    )

    now = time.monotonic()

    with LOCK:
        hit = CACHE.get(cache_key)

        if (
            hit
            and now - hit[0] < TTL[endpoint]
        ):
            return hit[1]

    response = requests.get(
        BASE + "/" + endpoint,
        params=params,
        timeout=12,
        headers={
            "Accept": "application/json",
            "User-Agent": "FlyHopGo/1.0"
        }
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            "Unexpected response from data provider"
        )

    with LOCK:
        CACHE[cache_key] = (
            now,
            payload
        )

    return payload


def failure(exc):
    logger.warning(
        "Radar data unavailable: %s",
        exc
    )

    return jsonify({
        "error": (
            "Flight data is temporarily unavailable. "
            "Please try again."
        )
    }), 502


# --------------------------------------------------
# API ROUTES
# --------------------------------------------------

@radar_bp.get("/api/radar/status")
def status():
    try:
        return jsonify(
            radar_get("status")
        )

    except (
        requests.RequestException,
        ValueError
    ) as exc:
        return failure(exc)


@radar_bp.get("/api/radar/graph")
def graph():
    try:
        data = radar_get("graph")

        return jsonify(
            enrich_graph(data)
        )

    except (
        requests.RequestException,
        ValueError
    ) as exc:
        return failure(exc)


@radar_bp.get("/api/radar/flights")
def flights():
    origin = request.args.get(
        "from", ""
    ).strip()

    dest = request.args.get(
        "to", ""
    ).strip()

    if (
        not origin
        or not dest
        or len(origin) > 120
        or len(dest) > 120
    ):
        return jsonify({
            "error": (
                "Choose a valid departure "
                "and destination."
            )
        }), 400

    try:
        return jsonify(
            radar_get(
                "flights",
                {
                    "from": origin,
                    "to": dest
                }
            )
        )

    except (
        requests.RequestException,
        ValueError
    ) as exc:
        return failure(exc)


@radar_bp.get("/api/radar/connections")
def connections():
    origin = request.args.get(
        "from", ""
    ).strip()

    dest = request.args.get(
        "to", ""
    ).strip()

    stops = request.args.get(
        "stops", "1"
    )

    if (
        not origin
        or not dest
        or len(origin) > 120
        or len(dest) > 120
        or stops not in ("1", "2")
    ):
        return jsonify({
            "error": (
                "Choose two cities "
                "and 1 or 2 stops."
            )
        }), 400

    try:
        data = radar_get(
            "connections",
            {
                "from": origin,
                "to": dest,
                "stops": stops
            }
        )

        return jsonify(
            enrich_connections(data)
        )

    except (
        requests.RequestException,
        ValueError
    ) as exc:
        return failure(exc)
