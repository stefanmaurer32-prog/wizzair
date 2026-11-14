
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify

# --------------------------------------------------
# FLYHOPGO - 72-HOUR FLIGHT OVERVIEW
# --------------------------------------------------

today_bp = Blueprint("today_routes", __name__)

TIMEZONE = ZoneInfo("Europe/Zurich")
WINDOW_HOURS = 72


# --------------------------------------------------
# CURRENT SEARCH WINDOW
# --------------------------------------------------

def current_window():
    now = datetime.now(TIMEZONE)
    end = now + timedelta(hours=WINDOW_HOURS)

    return now, end


# --------------------------------------------------
# FLIGHT DATA
# --------------------------------------------------

def get_available_flights(start, end):
    """
    Placeholder for the AYCF flight data integration.

    No flights are returned until a verified
    data source has been connected.
    """

    return []


# --------------------------------------------------
# 72-HOUR API
# --------------------------------------------------

@today_bp.get("/api/radar/today")
def daily_routes():

    start, end = current_window()

    try:
        flights = get_available_flights(start, end)

        return jsonify({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hours": WINDOW_HOURS,
            "state": "ready",
            "routes": flights,
            "processed": 0,
            "total": 0,
            "complete": True,
            "error": None,
            "data_available": False,
            "note": (
                "The 72-hour API is working. "
                "Live flight data is not yet connected. "
                "No flight availability is confirmed."
            )
        })

    except Exception:

        today_bp.logger.exception(
            "72-hour flight overview failed"
        )

        return jsonify({
            "state": "error",
            "routes": [],
            "processed": 0,
            "total": 0,
            "complete": False,
            "error": "Flight overview temporarily unavailable."
        }), 500


# --------------------------------------------------
# API HEALTH CHECK
# --------------------------------------------------

@today_bp.get("/api/radar/today/health")
def today_health():

    return jsonify({
        "status": "ok",
        "service": "FlyHopGo 72-hour overview",
        "hours": WINDOW_HOURS,
        "data_connected": False
    })
