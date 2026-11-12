
from flask import Flask, jsonify, render_template
from urllib.request import Request, urlopen
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import os
import re
import time
import threading
import pdfplumber

from aycf_radar import radar_bp

app = Flask(__name__)
app.register_blueprint(radar_bp)

URL = "https://multipass.wizzair.com/aycf-availability.pdf"
CACHE_SECONDS = 3600

cache = {
    "at": 0,
    "routes": [],
    "period": "",
    "updated": ""
}

cache_lock = threading.Lock()


def english_datetime():
    now = datetime.now(ZoneInfo("Europe/Zurich"))
    months = [
        "Jan", "Feb", "Mar", "Apr",
        "May", "Jun", "Jul", "Aug",
        "Sep", "Oct", "Nov", "Dec"
    ]
    month = months[now.month - 1]

    return (
        f"{now.day:02d} {month} {now.year}, "
        f"{now.strftime('%I:%M %p')}"
    )


def fetch_routes():
    with cache_lock:
        if (
            cache["routes"]
            and time.time() - cache["at"] < CACHE_SECONDS
        ):
            return dict(cache)

        req = Request(
            URL,
            headers={
                "User-Agent": "Mozilla/5.0 WizzRouteExplorer/1.0"
            }
        )

        with urlopen(req, timeout=25) as response:
            raw = response.read(5_000_000)

        if not raw.startswith(b"%PDF"):
            raise ValueError(
                "Wizz Air did not return a valid PDF."
            )

        routes = set()

        with pdfplumber.open(BytesIO(raw)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        if not row:
                            continue

                        cells = [
                            re.sub(
                                r"\s+", " ", str(c or "")
                            ).strip()
                            for c in row
                        ]

                        for i in range(0, len(cells) - 1, 2):
                            a, b = cells[i:i + 2]

                            if (
                                a and b
                                and a.lower() not in (
                                    "departure city", "departure"
                                )
                                and b.lower() not in (
                                    "arrival city", "arrival"
                                )
                                and len(a) < 65
                                and len(b) < 65
                            ):
                                routes.add((a, b))

        if not routes:
            raise ValueError(
                "No flight routes could be extracted."
            )

        cache.update(
            at=time.time(),
            routes=sorted(routes),
            period="",
            updated=english_datetime()
        )

        return dict(cache)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/routes")
def api_routes():
    try:
        data = fetch_routes()

        return jsonify({
            "routes": data["routes"],
            "period": data["period"],
            "updated": data["updated"],
            "source": URL,
            "count": len(data["routes"]),
            "note": (
                "Official route list only. "
                "Flight schedules, connections and "
                "seat availability are not guaranteed."
            )
        })

    except Exception as exc:
        app.logger.error("Route loading error: %s", exc)

        return jsonify({
            "error": "Route list temporarily unavailable.",
            "source": URL
        }), 503


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "FlyHopGo"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
