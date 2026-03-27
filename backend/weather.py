import os
import json
import time
import logging
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("mar_hvac.weather")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OW_BASE_URL         = "https://api.openweathermap.org/data/2.5"

# forecast_cache.json lives inside the backend/ folder
CACHE_FILE_PATH = Path(__file__).parent / "forecast_cache.json"

# How old can the saved forecast be before we consider it expired?
FORECAST_MAX_AGE_HOURS = 168   # 7 days = 168 hours


# ─────────────────────────────────────────────────────────────
# 1. FETCH CURRENT WEATHER (live)
# ─────────────────────────────────────────────────────────────

def fetch_current_weather(lat: float, lon: float) -> Optional[dict]:
    """
    Fetch current weather conditions from OpenWeather API.
    """
    if not OPENWEATHER_API_KEY:
        logger.warning("[WEATHER] No API key set in .env file.")
        return None

    try:
        response = requests.get(
            f"{OW_BASE_URL}/weather",
            params={
                "lat":   lat,
                "lon":   lon,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric",
            },
            timeout=5
        )
        response.raise_for_status()

        data = response.json()
        result = {
            "temp":        data["main"]["temp"],
            "humidity":    data["main"]["humidity"],
            "solar":       400.0,
            "description": data["weather"][0]["description"],
            "fetched_at":  time.time(),
        }
        logger.info(f"[WEATHER] Live: {result['temp']}C @ ({lat},{lon})")
        return result

    except Exception as e:
        logger.error(f"[WEATHER] Live fetch failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 2. FETCH AND SAVE 7-DAY FORECAST  (the Starlink buffer)
# ─────────────────────────────────────────────────────────────

def fetch_7day_forecast(lat: float, lon: float) -> list[dict]:
    """Fetch 5-day / 3-hour forecast from OpenWeather API."""
    if not OPENWEATHER_API_KEY:
        return []

    try:
        response = requests.get(
            f"{OW_BASE_URL}/forecast",
            params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=10
        )
        response.raise_for_status()

        items = response.json().get("list", [])
        return [
            {
                "ts":          item["dt"],
                "temp":        item["main"]["temp"],
                "humidity":    item["main"]["humidity"],
                "description": item["weather"][0]["description"],
                "solar":       400.0,
            }
            for item in items
        ]
    except Exception as e:
        logger.error(f"[FORECAST] Fetch error: {e}")
        return []


def save_forecast_cache(lat: float, lon: float, points: list[dict]) -> bool:
    """Save forecast points to forecast_cache.json."""
    if not points:
        return False

    data_to_save = {
        "saved_at":    time.time(),
        "lat":         lat,
        "lon":         lon,
        "point_count": len(points),
        "points":      points,
    }

    try:
        with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)
        return True
    except Exception:
        return False


def fetch_and_save_7day_forecast(lat: float, lon: float) -> bool:
    """Convenience function: fetch AND save to disk."""
    points = fetch_7day_forecast(lat, lon)
    return save_forecast_cache(lat, lon, points)


# ─────────────────────────────────────────────────────────────
# 3. LOAD SAVED FORECAST  (offline fallback)
# ─────────────────────────────────────────────────────────────

def load_forecast_cache() -> Optional[dict]:
    """Load the saved forecast from forecast_cache.json."""
    if not CACHE_FILE_PATH.exists():
        return None

    try:
        with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        age_hours = (time.time() - data["saved_at"]) / 3600
        if age_hours > FORECAST_MAX_AGE_HOURS:
            return None
        return data
    except Exception:
        return None


def get_cache_age_hours() -> Optional[float]:
    """Age of the saved forecast cache in hours."""
    cache = load_forecast_cache()
    if not cache:
        return None
    return round((time.time() - cache["saved_at"]) / 3600, 1)


# ─────────────────────────────────────────────────────────────
# 4. LOOK UP DATA FROM SAVED FORECAST
# ─────────────────────────────────────────────────────────────

def get_temp_for_hours_ahead(hours_ahead: float = 0.0) -> Optional[float]:
    """Predicted temperature for N hours in the future."""
    cache = load_forecast_cache()
    if not cache or not cache.get("points"):
        return None

    target_ts = time.time() + (hours_ahead * 3600)
    closest = min(cache["points"], key=lambda p: abs(p["ts"] - target_ts))
    return closest["temp"]


def get_forecast_summary_for_chart() -> list[dict]:
    """Return all forecast points for the Streamlit chart."""
    cache = load_forecast_cache()
    return cache.get("points", []) if cache else []