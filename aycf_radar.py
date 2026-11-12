
"""AYCF Radar integration for existing FlyHopGo Flask app.
Register: from aycf_radar import radar_bp; app.register_blueprint(radar_bp)
"""
import time
import threading
import requests
from flask import Blueprint, jsonify, request

radar_bp = Blueprint('radar', __name__)
BASE = 'https://aycfradar.com/api'
CACHE = {}
LOCK = threading.Lock()
TTL = {'status': 120, 'graph': 600, 'flights': 90, 'connections': 90}


def radar_get(endpoint, params=None):
    params = params or {}
    key = (endpoint, tuple(sorted(params.items())))
    now = time.monotonic()
    with LOCK:
        hit = CACHE.get(key)
        if hit and now - hit[0] < TTL[endpoint]:
            return hit[1]
    response = requests.get(BASE + '/' + endpoint, params=params, timeout=12,
                            headers={'Accept': 'application/json', 'User-Agent': 'FlyHopGo/1.0'})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError('Unexpected response from data provider')
    with LOCK:
        CACHE[key] = (now, payload)
    return payload


def failure(exc):
    radar_bp.logger.warning('AYCF Radar unavailable: %s', exc) if hasattr(radar_bp, 'logger') else None
    return jsonify({'error': 'AYCF Radar is temporarily unavailable. Please try again.'}), 502


@radar_bp.get('/api/radar/status')
def status():
    try:
        return jsonify(radar_get('status'))
    except (requests.RequestException, ValueError) as exc:
        return failure(exc)


@radar_bp.get('/api/radar/graph')
def graph():
    try:
        return jsonify(radar_get('graph'))
    except (requests.RequestException, ValueError) as exc:
        return failure(exc)


@radar_bp.get('/api/radar/flights')
def flights():
    origin = request.args.get('from', '').strip()
    dest = request.args.get('to', '').strip()
    if not origin or not dest or len(origin) > 120 or len(dest) > 120:
        return jsonify({'error': 'Choose a valid departure and destination.'}), 400
    try:
        return jsonify(radar_get('flights', {'from': origin, 'to': dest}))
    except (requests.RequestException, ValueError) as exc:
        return failure(exc)


@radar_bp.get('/api/radar/connections')
def connections():
    origin = request.args.get('from', '').strip()
    dest = request.args.get('to', '').strip()
    stops = request.args.get('stops', '1')
    if not origin or not dest or len(origin) > 120 or len(dest) > 120 or stops not in ('1', '2'):
        return jsonify({'error': 'Choose two cities and 1 or 2 stops.'}), 400
    try:
        return jsonify(radar_get('connections', {'from': origin, 'to': dest, 'stops': stops}))
    except (requests.RequestException, ValueError) as exc:
        return failure(exc)
