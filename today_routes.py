
"""
FlyHopGo - Direct flights in the next 72 hours.

Uses the existing AYCF Radar integration.
Scans routes in the background and returns
progress plus matching flight records.

Register in app.py:
    from today_routes import today_bp
    app.register_blueprint(today_bp)
"""

import logging
import threading
import time

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Blueprint, jsonify

from aycf_radar import radar_get

today_bp = Blueprint("today_routes", __name__)

logger = logging.getLogger(__name__)

ZONE = ZoneInfo("Europe/Zurich")
HOURS = 72
CACHE_SECONDS = 900

# Small delay to avoid overloading the provider.
REQUEST_DELAY = 0.2

LOCK = threading.Lock()

STATE = {
    "state": "idle",
    "routes": [],
    "processed": 0,
    "total": 0,
    "updated": None,
    "started": None,
    "start": None,
    "end": None,
    "error": None,
    "scan_id": 0
}


def current_window():
    start = datetime.now(ZONE)
    end = start + timedelta(hours=HOURS)
    return start, end


def parse_flight_datetime(date_value, time_value):
    if not isinstance(date_value, str):
        return None

    if not isinstance(time_value, str):
        return None

    try:
        date_part = date_value.strip()[:10]
        time_part = time_value.strip()[:5]

        return datetime.strptime(
            date_part + " " + time_part,
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ZONE)

    except ValueError:
        return None


def get_route_pairs(graph):
    nodes = graph.get("nodes", [])

    if not isinstance(nodes, list):
        raise ValueError("Invalid graph nodes")

    pairs = set()

    for node in nodes:
        if not isinstance(node, dict):
            continue

        origin = node.get("city")
        destinations = node.get("dests", [])

        if not isinstance(origin, str):
            continue

        if not isinstance(destinations, list):
            continue

        origin = origin.strip()

        for destination in destinations:
            if not isinstance(destination, str):
                continue

            destination = destination.strip()

            if (
                origin
                and destination
                and origin != destination
            ):
                pairs.add((origin, destination))

    return sorted(pairs)


def scan_flights(scan_id, start, end):
    found = {}
    failed = 0

    try:
        graph = radar_get("graph")
        pairs = get_route_pairs(graph)

        if not pairs:
            raise ValueError(
                "No routes found in the radar graph"
            )

        with LOCK:
            if STATE["scan_id"] != scan_id:
                return

            STATE["total"] = len(pairs)

        for index, (origin, destination) in enumerate(
            pairs, start=1
        ):
            with LOCK:
                if STATE["scan_id"] != scan_id:
                    return

            try:
                payload = radar_get(
                    "flights",
                    {
                        "from": origin,
                        "to": destination
                    }
                )

                flights = payload.get("flights", [])

                if (
                    payload.get("available")
                    and isinstance(flights, list)
                ):
                    for flight in flights:
                        if not isinstance(flight, dict):
                            continue

                        date_value = flight.get("date")
                        time_value = flight.get("time")

                        departure = parse_flight_datetime(
                            date_value,
                            time_value
                        )

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
                    "Flight scan failed for %s -> %s: %s",
                    origin,
                    destination,
                    exc
                )

            with LOCK:
                if STATE["scan_id"] != scan_id:
                    return

                STATE["processed"] = index

                STATE["routes"] = sorted(
                    found.values(),
                    key=lambda item: (
                        item["date"],
                        item["time"],
                        item["from"],
                        item["to"]
                    )
                )

            time.sleep(REQUEST_DELAY)

        with LOCK:
            if STATE["scan_id"] != scan_id:
                return

            STATE["updated"] = time.time()

            if failed == len(pairs):
                STATE["state"] = "error"
                STATE["error"] = (
                    "All flight requests failed."
                )
            else:
                STATE["state"] = "ready"

                if failed:
                    STATE["error"] = (
                        f"{failed} routes could not "
                        "be checked. Results may "
                        "be incomplete."
                    )

    except Exception:
        logger.exception(
            "FlyHopGo 72-hour scan failed"
        )

        with LOCK:
            if STATE["scan_id"] != scan_id:
                return

            STATE["state"] = "error"
            STATE["updated"] = time.time()
            STATE["error"] = (
                "Unable to retrieve the flight "
                "overview from AYCF Radar."
            )


def start_scan():
    start, end = current_window()

    STATE["scan_id"] += 1
    scan_id = STATE["scan_id"]

    STATE.update({
        "state": "loading",
        "routes": [],
        "processed": 0,
        "total": 0,
        "updated": None,
        "started": time.time(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "error": None
    })

    thread = threading.Thread(
        target=scan_flights,
        args=(scan_id, start, end),
        daemon=True
    )

    thread.start()


@today_bp.get("/api/radar/today")
def daily_routes():
    with LOCK:
        now = time.time()

        expired = (
            STATE["updated"] is not None
            and now - STATE["updated"]
            >= CACHE_SECONDS
        )

        stale_loading = (
            STATE["state"] == "loading"
            and STATE["started"] is not None
            and now - STATE["started"] > 1800
        )

        if (
            STATE["state"] == "idle"
            or expired
            or stale_loading
        ):
            start_scan()

        return jsonify({
            "state": STATE["state"],
            "routes": list(STATE["routes"]),
            "processed": STATE["processed"],
            "total": STATE["total"],
            "complete": (
                STATE["state"] == "ready"
            ),
            "start": STATE["start"],
            "end": STATE["end"],
            "hours": HOURS,
            "error": STATE["error"],
            "note": (
                "Flight times are reported by "
                "the external AYCF Radar service. "
                "AYCF seat availability is not "
                "guaranteed. Verify each flight "
                "with Wizz Air before booking."
            )
        })


@today_bp.get("/api/radar/today/health")
def today_health():
    with LOCK:
        return jsonify({
            "status": "ok",
            "service": "FlyHopGo 72-hour overview",
            "state": STATE["state"],
            "processed": STATE["processed"],
            "total": STATE["total"],
            "flights": len(STATE["routes"])
        })
