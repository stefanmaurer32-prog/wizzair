
"""
FlyHopGo - 72-hour departures by selected airport.

The scan starts only after the user selects
a departure airport.

Existing aycf_radar.py remains unchanged.
"""

import logging
import threading
import time

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Blueprint, jsonify, request

from aycf_radar import radar_get

today_bp = Blueprint("today_routes", __name__)

logger = logging.getLogger(__name__)

ZONE = ZoneInfo("Europe/Zurich")
HOURS = 72
CACHE_SECONDS = 900
REQUEST_DELAY = 0.15

LOCK = threading.Lock()
SCANS = {}


def window():
    now = datetime.now(ZONE)
    return now, now + timedelta(hours=HOURS)


def get_airports():
    graph = radar_get("graph")
    nodes = graph.get("nodes", [])

    if not isinstance(nodes, list):
        raise ValueError("Invalid airport graph")

    airports = {}

    for node in nodes:
        if not isinstance(node, dict):
            continue

        city = node.get("city")
        destinations = node.get("dests")

        if not isinstance(city, str):
            continue

        if not isinstance(destinations, list):
            continue

        city = city.strip()

        valid_destinations = sorted({
            dest.strip()
            for dest in destinations
            if isinstance(dest, str)
            and dest.strip()
            and dest.strip() != city
        })

        if not city or not valid_destinations:
            continue

        airports[city] = {
            "city": city,
            "country": node.get("country") or "",
            "iata": node.get("iata") or "",
            "destinations": valid_destinations
        }

    return airports


def parse_departure(flight):
    if not isinstance(flight, dict):
        return None

    date_value = flight.get("date")
    time_value = flight.get("time")

    if not isinstance(date_value, str):
        return None

    if not isinstance(time_value, str):
        return None

    try:
        return datetime.strptime(
            date_value[:10] + " " + time_value[:5],
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ZONE)

    except ValueError:
        return None


def scan_airport(origin, destinations, start, end):
    found = {}
    failed = 0

    try:
        for index, destination in enumerate(
            destinations, start=1
        ):
            try:
                data = radar_get(
                    "flights",
                    {
                        "from": origin,
                        "to": destination
                    }
                )

                flights = data.get("flights", [])

                if (
                    data.get("available")
                    and isinstance(flights, list)
                ):
                    for flight in flights:
                        departure = parse_departure(flight)

                        if departure is None:
                            continue

                        if not start <= departure < end:
                            continue

                        record = {
                            "from": origin,
                            "to": destination,
                            "date": departure.strftime(
                                "%Y-%m-%d"
                            ),
                            "time": departure.strftime(
                                "%H:%M"
                            )
                        }

                        key = (
                            origin,
                            destination,
                            record["date"],
                            record["time"]
                        )

                        found[key] = record

            except (
                requests.RequestException,
                ValueError,
                TypeError
            ) as exc:
                failed += 1
                logger.warning(
                    "Flight lookup failed: %s -> %s: %s",
                    origin,
                    destination,
                    exc
                )

            with LOCK:
                state = SCANS.get(origin)

                if state is None:
                    return

                state["processed"] = index
                state["routes"] = sorted(
                    found.values(),
                    key=lambda item: (
                        item["date"],
                        item["time"],
                        item["to"]
                    )
                )

            time.sleep(REQUEST_DELAY)

        with LOCK:
            state = SCANS.get(origin)

            if state is None:
                return

            state["updated"] = time.time()

            if failed == len(destinations):
                state["state"] = "error"
                state["error"] = (
                    "All flight requests failed."
                )
            else:
                state["state"] = "ready"

                if failed:
                    state["error"] = (
                        f"{failed} destinations could "
                        "not be checked. Results "
                        "may be incomplete."
                    )

    except Exception:
        logger.exception(
            "Departure scan failed for %s",
            origin
        )

        with LOCK:
            state = SCANS.get(origin)

            if state is not None:
                state["state"] = "error"
                state["error"] = (
                    "Flight search temporarily unavailable."
                )
                state["updated"] = time.time()


@today_bp.get("/api/radar/airports")
def departure_airports():
    try:
        airports = get_airports()

        return jsonify({
            "airports": [
                {
                    "city": item["city"],
                    "country": item["country"],
                    "iata": item["iata"]
                }
                for item in sorted(
                    airports.values(),
                    key=lambda item: item["city"]
                )
            ]
        })

    except (
        requests.RequestException,
        ValueError,
        TypeError
    ):
        logger.exception("Airport list failed")

        return jsonify({
            "error": "Airport list unavailable.",
            "airports": []
        }), 502


@today_bp.get("/api/radar/today")
def daily_routes():
    origin = request.args.get("from", "").strip()

    if not origin:
        return jsonify({
            "state": "idle",
            "routes": [],
            "processed": 0,
            "total": 0,
            "complete": False,
            "error": None,
            "note": "Select a departure airport to search."
        })

    if len(origin) > 120:
        return jsonify({
            "error": "Invalid departure airport."
        }), 400

    try:
        airports = get_airports()

    except (
        requests.RequestException,
        ValueError,
        TypeError
    ):
        logger.exception("Unable to load airport graph")

        return jsonify({
            "state": "error",
            "routes": [],
            "error": "Airport data unavailable."
        }), 502

    if origin not in airports:
        return jsonify({
            "error": "Unknown departure airport."
        }), 400

    destinations = airports[origin]["destinations"]

    with LOCK:
        state = SCANS.get(origin)
        now = time.time()

        expired = (
            state is not None
            and state["updated"] is not None
            and now - state["updated"] >= CACHE_SECONDS
        )

        stale_loading = (
            state is not None
            and state["state"] == "loading"
            and now - state["started"] > 600
        )

        if state is None or expired or stale_loading:
            start, end = window()

            state = {
                "state": "loading",
                "routes": [],
                "processed": 0,
                "total": len(destinations),
                "started": now,
                "updated": None,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "error": None
            }

            SCANS[origin] = state

            threading.Thread(
                target=scan_airport,
                args=(
                    origin,
                    destinations,
                    start,
                    end
                ),
                daemon=True
            ).start()

        return jsonify({
            "state": state["state"],
            "from": origin,
            "routes": list(state["routes"]),
            "processed": state["processed"],
            "total": state["total"],
            "complete": state["state"] == "ready",
            "start": state["start"],
            "end": state["end"],
            "hours": HOURS,
            "error": state["error"],
            "note": (
                "Flight information is supplied by "
                "AYCF Radar. Booking availability "
                "must be checked with Wizz Air."
            )
        })


@today_bp.get("/api/radar/today/health")
def today_health():
    return jsonify({
        "status": "ok",
        "service": "FlyHopGo departure search",
        "mode": "airport-specific"
    })
