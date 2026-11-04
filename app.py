
import os
import re
import time
import threading

from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO

import requests
import pdfplumber

from flask import Flask, jsonify, render_template


app = Flask(__name__)

# -----------------------------------------
# SETTINGS
# -----------------------------------------

PDF_URL = (
    "https://multipass.wizzair.com/"
    "aycf-availability.pdf"
)

TIMEZONE = ZoneInfo("Europe/Zurich")

CACHE_SECONDS = 3600

cache = {
    "routes": [],
    "count": 0,
    "period": "",
    "updated": "",
    "timestamp": 0,
}

cache_lock = threading.Lock()


# -----------------------------------------
# ENGLISH DATE AND TIME WITH AM / PM
# -----------------------------------------

def english_datetime():
    now = datetime.now(TIMEZONE)

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


# -----------------------------------------
# CLEAN TEXT
# -----------------------------------------

def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


# -----------------------------------------
# DOWNLOAD OFFICIAL WIZZ AIR PDF
# -----------------------------------------

def download_pdf():

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/pdf,*/*",
    }

    response = requests.get(
        PDF_URL,
        headers=headers,
        timeout=45
    )

    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        raise ValueError(
            "The Wizz Air server did not return a valid PDF."
        )

    return response.content


# -----------------------------------------
# EXTRACT ROUTES FROM PDF
# -----------------------------------------

def extract_routes(pdf_content):

    routes = set()
    period = ""

    with pdfplumber.open(
        BytesIO(pdf_content)
    ) as pdf:

        for page in pdf.pages:

            text = page.extract_text() or ""

            # Look for a validity period
            if not period:

                match = re.search(
                    r"(?:valid|period|availability)"
                    r"[^\n]{0,100}",
                    text,
                    re.IGNORECASE
                )

                if match:
                    period = clean_text(
                        match.group(0)
                    )

            # Extract structured PDF tables
            tables = page.extract_tables()

            for table in tables:

                for row in table:

                    if not row:
                        continue

                    values = [
                        clean_text(cell)
                        for cell in row
                    ]

                    values = [
                        value for value in values
                        if value
                    ]

                    if len(values) < 2:
                        continue

                    origin = values[0]
                    destination = values[1]

                    if not valid_airport(origin):
                        continue

                    if not valid_airport(destination):
                        continue

                    if origin.lower() == destination.lower():
                        continue

                    routes.add(
                        (origin, destination)
                    )

            # Fallback for simple text lines
            for line in text.splitlines():

                line = clean_text(line)

                # Example: London - Budapest
                match = re.match(
                    r"^(.+?)\s+(?:-|–|—|→)\s+(.+?)$",
                    line
                )

                if match:

                    origin = clean_text(
                        match.group(1)
                    )

                    destination = clean_text(
                        match.group(2)
                    )

                    if (
                        valid_airport(origin)
                        and valid_airport(destination)
                        and origin.lower() != destination.lower()
                    ):
                        routes.add(
                            (origin, destination)
                        )

    return sorted(routes), period


# -----------------------------------------
# VALIDATE AIRPORT / CITY NAMES
# -----------------------------------------

def valid_airport(name):

    if not name:
        return False

    if len(name) < 3 or len(name) > 80:
        return False

    if not re.search(r"[A-Za-z]", name):
        return False

    if re.search(r"https?://|www\.", name, re.I):
        return False

    if re.search(
        r"^(from|to|origin|destination|"
        r"departure|arrival|route|date|"
        r"airport|city)$",
        name,
        re.I
    ):
        return False

    return True


# -----------------------------------------
# LOAD AND CACHE ROUTES
# -----------------------------------------

def get_routes():

    with cache_lock:

        now = time.time()

        if (
            cache["routes"]
            and now - cache["timestamp"] < CACHE_SECONDS
        ):
            return dict(cache)

        try:

            pdf_content = download_pdf()

            routes, period = extract_routes(
                pdf_content
            )

            if not routes:
                raise ValueError(
                    "No flight routes could be extracted "
                    "from the official PDF."
                )

            cache["routes"] = routes
            cache["count"] = len(routes)
            cache["period"] = period
            cache["updated"] = english_datetime()
            cache["timestamp"] = now

            print(
                f"Loaded {len(routes)} Wizz Air routes",
                flush=True
            )

        except Exception as error:

            print(
                f"Wizz Air PDF error: {error}",
                flush=True
            )

            if not cache["routes"]:
                raise

        return dict(cache)


# -----------------------------------------
# HOMEPAGE
# -----------------------------------------

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# -----------------------------------------
# API FOR ROUTE EXPLORER
# -----------------------------------------

@app.route("/api/routes")
def api_routes():

    try:

        data = get_routes()

        return jsonify({
            "routes": data["routes"],
            "count": data["count"],
            "period": data["period"],
            "updated": data["updated"],
            "source": PDF_URL,
        })

    except Exception as error:

        return jsonify({
            "error": str(error),
            "routes": [],
            "count": 0,
        }), 503


# -----------------------------------------
# HEALTH CHECK
# -----------------------------------------

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "Wizz Air Route Explorer",
    })


# -----------------------------------------
# START APPLICATION
# -----------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
