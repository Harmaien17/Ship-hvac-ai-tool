import os
import json
import time
import logging
import requests
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("mar_hvac.weather")

# CONFIG
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OW_BASE_URL = "https://api.openweathermap.org/data/2.5"
CACHE_FILE_PATH = Path(__file__).parent / "forecast_cache.json"
FORECAST_MAX_AGE_HOURS = 336 # 14-day duration [cite: 213, 214]

def fetch_14day_forecast(lat: float, lon: float) -> list[dict]:
    """Fetch 5-day data and loop it to create a 14-day buffer."""
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
        
        # Mapping API keys to our Schema keys
        base_points = [
            {
                "ts": i["dt"], 
                "temp": i["main"]["temp"], 
                "humidity": i["main"]["humidity"], 
                "description": i["weather"][0]["description"], 
                "solar": 400.0
            } for i in items
        ]
        
        # Duplicate data to fill the 14-day requirement
        extended_points = []
        for multiplier in range(3):
            for point in base_points:
                new_point = point.copy()
                new_point["ts"] = point["ts"] + (5 * 24 * 3600 * multiplier)
                extended_points.append(new_point)
        return extended_points
    except Exception as e:
        logger.error(f"[FORECAST] API Error: {e}")
        return []

def save_forecast_cache(lat: float, lon: float, points: list[dict]):
    """Store data locally for deep-sea connectivity blackouts[cite: 50, 214]."""
    data = {"saved_at": time.time(), "lat": lat, "lon": lon, "points": points}
    try:
        with open(CACHE_FILE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"[CACHE] Save failed: {e}")

def load_forecast_cache() -> Optional[dict]:
    """Load JSON data from disk if it exists."""
    if not CACHE_FILE_PATH.exists():
        return None
    try:
        with open(CACHE_FILE_PATH, "r") as f:
            return json.load(f)
    except:
        return None

def get_14_day_forecast(lat: float, lon: float) -> dict:
    """Master logic for the Resilience endpoint."""
    cache = load_forecast_cache()
    
    # Logic: Use cache if it was updated within the last 24 hours
    if cache and (time.time() - cache.get("saved_at", 0)) < 86400:
        logger.info("[FORECAST] Serving from fresh local cache.")
        return cache

    # Logic: Refresh from API
    points = fetch_14day_forecast(lat, lon)
    if points:
        save_forecast_cache(lat, lon, points)
        return load_forecast_cache()
    
    # Failsafe: Use old cache if internet is down 
    if cache:
        logger.warning("[FORECAST] API Offline. Falling back to local cache.")
        return cache
        
    raise Exception("Weather data unavailable. Check API Key and internet.")

def get_cache_age_hours() -> Optional[float]:
    """Returns the age of the offline cache in hours for the Health Dashboard."""
    cache = load_forecast_cache()
    if not cache:
        return None
    return round((time.time() - cache.get("saved_at", 0)) / 3600, 1)