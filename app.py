
from flask import Flask, jsonify, render_template
from urllib.request import Request, urlopen
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from functools import lru_cache

import unicodedata
import os
import re
import time
import threading

import pdfplumber
import airportsdata
import pycountry

# AYCF Radar integration
from aycf_radar import radar_bp

# New 72-hour flight overview
from today_routes import today_bp


# --------------------------------------------------
# FLASK APPLICATION
# --------------------------------------------------

app = Flask(__name__)

app.register_blueprint(radar_bp)
app.register_blueprint(today_bp)


# --------------------------------------------------
# WIZZ AIR PDF CONFIGURATION
# --------------------------------------------------

URL = (
    "https://multipass.wizzair.com/"
    "aycf-availability.pdf"
)

CACHE_SECONDS = 3600

cache = {
    "at": 0,
    "routes": [],
    "period": "",
    "updated": "",
    "airports": []
}

cache_lock = threading.Lock()


# --------------------------------------------------
# TEXT NORMALIZATION
# --------------------------------------------------

def normalize(value):
    value = unicodedata.normalize(
        "NFKD",
        str(value or "")
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip().casefold()


# --------------------------------------------------
# COUNTRY INFORMATION
# --------------------------------------------------

def country_name(code):
    if not code:
        return ""

    special = {
        "XK": "Kosovo",
        "GB": "United Kingdom",
        "CZ": "Czech Republic",
        "TR": "Turkey",
        "MD": "Moldova",
        "MK": "North Macedonia"
    }

    code = str(code).upper()

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
            airport.get("country", "")
        )

        if not country:
            continue

        city = airport.get("city", "")
        name = airport.get("name", "")

        if city:
            by_city[
                normalize(city)
            ].add(country)

        if name:
            by_name[
                normalize(name)
            ].add(country)

    return airports, by_city, by_name


def airport_country(value):
    text = str(value or "").strip()

    if not text:
        return ""

    airports, by_city, by_name = (
        airport_database()
    )

    # Prefer explicit IATA airport code.
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
            airports[code].get(
                "country", ""
            )
        )

    normalized = normalize(text)

    # Exact city match.
    countries = by_city.get(
        normalized,
        set()
    )

    if len(countries) == 1:
        return next(iter(countries))

    # Exact airport name.
    countries = by_name.get(
        normalized,
        set()
    )

    if len(countries) == 1:
        return next(iter(countries))

    # Airport names beginning with city.
    matches = set()

    for city, country_set in by_city.items():
        if normalized.startswith(city + " "):
            matches.update(country_set)

    if len(matches) == 1:
        return next(iter(matches))

    # Avoid guessing ambiguous locations.
    return ""


# --------------------------------------------------
# AIRPORT METADATA
# --------------------------------------------------

def build_airport_metadata(routes):
    cities = set()

    for departure, arrival in routes:
        cities.add(departure)
        cities.add(arrival)

    result = []

    for city in sorted(cities):
        result.append({
            "city": city,
            "country": airport_country(city)
        })

    return result


# --------------------------------------------------
# LAST UPDATE TIME
# --------------------------------------------------

def english_datetime():
    now = datetime.now(
        ZoneInfo("Europe/Zurich")
    )

    months = [
        "Jan", "Feb", "Mar", "Apr",
        "May", "Jun", "Jul", "Aug",
        "Sep", "Oct", "Nov", "Dec"
    ]

    month = months[now.month - 1]

    return (
        f"{now.day:02d} "
        f"{month} "
        f"{now.year}, "
        f"{now.strftime('%I:%M %p')}"
    )


# --------------------------------------------------
# FETCH OFFICIAL WIZZ AIR ROUTES
# --------------------------------------------------

def fetch_routes():
    with cache_lock:

        if (
            cache["routes"]
            and time.time() - cache["at"]
            < CACHE_SECONDS
        ):
            return dict(cache)

        req = Request(
            URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "WizzRouteExplorer/1.0"
                )
            }
        )

        with urlopen(
            req,
            timeout=25
        ) as response:

            raw = response.read(
                5_000_000
            )

        if not raw.startswith(b"%PDF"):
            raise ValueError(
                "Wizz Air did not return "
                "a valid PDF."
            )

        routes = set()

        with pdfplumber.open(
            BytesIO(raw)
        ) as pdf:

            for page in pdf.pages:

                for table in (
                    page.extract_tables()
                ):

                    for row in table:

                        if not row:
                            continue

                        cells = [
                            re.sub(
                                r"\s+",
                                " ",
                                str(c or "")
                            ).strip()
                            for c in row
                        ]

                        for i in range(
                            0,
                            len(cells) - 1,
                            2
                        ):

                            a, b = cells[
                                i:i + 2
                            ]

                            if (
                                a
                                and b
                                and a.lower() not in (
                                    "departure city",
                                    "departure"
                                )
                                and b.lower() not in (
                                    "arrival city",
                                    "arrival"
                                )
                                and len(a) < 65
                                and len(b) < 65
                            ):
                                routes.add(
                                    (a, b)
                                )

        if not routes:
            raise ValueError(
                "No flight routes "
                "could be extracted."
            )

        sorted_routes = sorted(
            routes
        )

        airport_metadata = (
            build_airport_metadata(
                sorted_routes
            )
        )

        cache.update(
            at=time.time(),
            routes=sorted_routes,
            period="",
            updated=english_datetime(),
            airports=airport_metadata
        )

        return dict(cache)


# --------------------------------------------------
# WEBSITE
# --------------------------------------------------

@app.get("/")
def index():
    return render_template(
        "index.html"
    )


# --------------------------------------------------
# OFFICIAL ROUTES API
# --------------------------------------------------

@app.get("/api/routes")
def api_routes():
    try:
        data = fetch_routes()

        return jsonify({
            "routes": data["routes"],
            "airports": data["airports"],
            "period": data["period"],
            "updated": data["updated"],
            "source": URL,
            "count": len(
                data["routes"]
            ),
            "note": (
                "Official route list only. "
                "Flight schedules, "
                "connections and seat "
                "availability are not "
                "guaranteed."
            )
        })

    except Exception as exc:
        app.logger.error(
            "Route loading error: %s",
            exc
        )

        return jsonify({
            "error": (
                "Route list temporarily "
                "unavailable."
            ),
            "source": URL
        }), 503


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "FlyHopGo"
    })


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
