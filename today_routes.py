import logging
import threading
import time

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Blueprint, jsonify

today_bp = Blueprint("today_routes", __name__)
