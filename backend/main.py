"""
MAR-HVAC AI — FastAPI Backend
backend/main.py

Run with:
  cd backend
  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Then open: http://localhost:8000/docs  (interactive API docs)

Endpoints:
  GET  /api/v1/health            — System health + weather cache status
  POST /api/v1/optimize          — Single cabin AI optimisation
  POST /api/v1/optimize/fleet    — Multi-cabin fleet optimisation
  GET  /api/v1/weather/update    — Manually refresh weather cache
  GET  /api/v1/weather/forecast  — 5-day forecast for dashboard chart
  GET  /api/v1/constants         — Engine constants for UI display
"""

import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import CabinTelemetry, HVACDecision, FleetSummary
from hvac_engine import (
    calculate_optimized_load,
    calculate_fleet_summary,
    update_weather_cache,
    get_cached_weather,
    GHOST_COOLING_FRACTION,
    U_HULL_INSULATED,
    U_HULL_BARE,
    ENGINE_RADIANT_W_M2,
    THERMAL_LAG_W_M2,
    METABOLIC_WATT,
    LATENT_CORRECTION,
    CACHE_EXPIRY_SECONDS,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mar_hvac.api")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OW_BASE_URL         = "https://api.openweathermap.org/data/2.5"


# ─────────────────────────────────────────────────────────────
# APP STARTUP / SHUTDOWN
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MAR-HVAC AI backend starting up...")
    if not OPENWEATHER_API_KEY:
        logger.warning("OPENWEATHER_API_KEY not set — weather will use fail-safe mode.")
    yield
    logger.info("MAR-HVAC AI backend shutting down.")


# ─────────────────────────────────────────────────────────────
# APP INSTANCE
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="MAR-HVAC AI",
    description=(
        "Intelligent Heat Load Optimisation for Marine Vessels. "
        "Eliminates Ghost Cooling. IMO 2030 compliant. "
        "Features: Ghost Cooling, Asset Defence, 7-Day Forecast Buffer, "
        "Dual Heating/Cooling, IoT Sensor Fusion."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow Streamlit (running on AJIJ's laptop on same LAN) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# WEATHER HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def fetch_live_weather(lat: float, lon: float) -> Optional[dict]:
    """
    Fetch current weather from OpenWeather API.
    Returns dict or None on ANY failure (timeout, no internet, bad key).
    All exceptions caught here — this is the fail-safe boundary.
    """
    if not OPENWEATHER_API_KEY:
        logger.warning("No API key — skipping live weather fetch.")
        return None
    try:
        resp = requests.get(
            f"{OW_BASE_URL}/weather",
            params={
                "lat":   lat,
                "lon":   lon,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric"
            },
            timeout=5   # Short timeout — ships have high-latency satellite links
        )
        resp.raise_for_status()
        d    = resp.json()
        temp = d["main"]["temp"]
        rh   = d["main"]["humidity"]
        solar = 400.0   # Placeholder — upgrade to One Call 3.0 for real solar data
        update_weather_cache(temp, rh, solar, source="openweather_api")
        logger.info(f"[WEATHER] Live fetch: {temp}C, {rh}%RH @ ({lat}, {lon})")
        return {"temp": temp, "humidity": rh, "solar": solar}
    except requests.exceptions.Timeout:
        logger.error("Weather API timeout — satellite link may be slow or down.")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Weather API connection error — vessel may be offline.")
        return None
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return None


def fetch_forecast(lat: float, lon: float) -> list[dict]:
    """
    Fetch 5-day / 3-hour forecast from OpenWeather.
    This is the data that gets saved as the 7-day Starlink buffer.
    Returns list of forecast points or empty list on failure.
    """
    if not OPENWEATHER_API_KEY:
        return []
    try:
        resp = requests.get(
            f"{OW_BASE_URL}/forecast",
            params={
                "lat":   lat,
                "lon":   lon,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric"
            },
            timeout=8
        )
        resp.raise_for_status()
        items = resp.json().get("list", [])
        return [
            {
                "ts":   item["dt"],
                "temp": item["main"]["temp"],
                "rh":   item["main"]["humidity"],
                "desc": item["weather"][0]["main"],
            }
            for item in items
        ]
    except Exception as e:
        logger.error(f"Forecast fetch failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/health")
def health_check():
    """
    System health check.
    Shows weather cache status, API key config, and backend version.
    Call this first to confirm the server is running.
    """
    cache, status = get_cached_weather()
    cache_age = round(time.time() - cache.timestamp, 1) if cache else None
    return {
        "status":             "online",
        "version":            "1.0.0",
        "api_key_configured": bool(OPENWEATHER_API_KEY),
        "weather_cache": {
            "status":      status,
            "age_seconds": cache_age,
            "source":      cache.source if cache else None,
            "temp":        cache.temperature if cache else None,
        },
        "timestamp": time.time(),
    }


@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize_single_cabin(
    telemetry: CabinTelemetry,
    lat:             float = 19.0760,   # Default: JNPT Mumbai
    lon:             float = 72.8777,
    refresh_weather: bool  = True
):
    """
    Optimise HVAC load for one cabin.

    - Attempts live weather fetch if external_temp not provided.
    - Falls back: live API -> 1hr cache -> 7-day forecast -> DHT22 + 5C.
    - Returns full AI decision with breakdown and reasoning log.

    Test this at: http://localhost:8000/docs -> POST /api/v1/optimize
    """
    logger.info(f"Optimize: cabin={telemetry.cabin_id}, occupied={telemetry.occupancy}")

    if telemetry.external_temp is None and refresh_weather:
        weather = fetch_live_weather(lat, lon)
        if weather:
            telemetry = telemetry.model_copy(update={"external_temp": weather["temp"]})

    try:
        decision = calculate_optimized_load(telemetry)
    except Exception as e:
        logger.exception(f"Engine error — cabin {telemetry.cabin_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Engine error: {e}")

    logger.info(
        f"Result: {decision.cabin_id} | {decision.mode.value} | "
        f"{decision.optimized_load_kw:.3f} kW | saved {decision.energy_saved_percent:.1f}%"
    )
    return decision


@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def optimize_fleet(
    cabin_list: list[CabinTelemetry],
    lat: float = 19.0760,
    lon: float = 72.8777,
):
    """
    Optimise HVAC for an entire fleet of cabins in one API call.
    Weather is fetched ONCE and shared across all cabins — efficient.
    """
    if not cabin_list:
        raise HTTPException(status_code=422, detail="cabin_list cannot be empty.")
    if len(cabin_list) > 500:
        raise HTTPException(status_code=422, detail="Max 500 cabins per request.")

    logger.info(f"Fleet optimize: {len(cabin_list)} cabins")

    weather = fetch_live_weather(lat, lon)
    if weather:
        cabin_list = [
            c.model_copy(update={"external_temp": weather["temp"]})
            if c.external_temp is None else c
            for c in cabin_list
        ]

    try:
        summary = calculate_fleet_summary(cabin_list)
    except Exception as e:
        logger.exception(f"Fleet engine error: {e}")
        raise HTTPException(status_code=500, detail=f"Fleet engine error: {e}")

    logger.info(
        f"Fleet result: {summary.total_load_kw:.2f} kW | "
        f"savings {summary.fleet_savings_percent:.1f}% | "
        f"ghost {summary.ghost_cooling_cabins}/{summary.total_cabins}"
    )
    return summary


@app.get("/api/v1/weather/update")
def weather_update(lat: float = 19.0760, lon: float = 72.8777):
    """
    Manually trigger a weather cache refresh.
    Call from the Streamlit 'Refresh Weather' button.
    """
    weather = fetch_live_weather(lat, lon)
    if weather:
        return {
            "success":   True,
            "temp":      weather["temp"],
            "humidity":  weather["humidity"],
            "solar":     weather["solar"],
            "cached_at": time.time(),
        }
    cache, status = get_cached_weather()
    return {
        "success":      False,
        "message":      "Live fetch failed — check satellite connection or API key.",
        "cache_status": status,
        "fallback_temp": cache.temperature if cache else None,
    }


@app.get("/api/v1/weather/forecast")
def weather_forecast(lat: float = 19.0760, lon: float = 72.8777):
    """
    Fetch 5-day forecast data for the dashboard chart.
    Also used by weather.py to populate the 7-day offline buffer.
    """
    points = fetch_forecast(lat, lon)
    return {
        "points": points,
        "count":  len(points),
    }


@app.get("/api/v1/constants")
def get_constants():
    """
    Expose engine constants for display in the Streamlit dashboard.
    Lets the UI show what values the AI is actually using.
    """
    return {
        "ghost_cooling_fraction": GHOST_COOLING_FRACTION,
        "u_hull_insulated":       U_HULL_INSULATED,
        "u_hull_bare":            U_HULL_BARE,
        "engine_radiant_w_m2":   ENGINE_RADIANT_W_M2,
        "thermal_lag_w_m2":      THERMAL_LAG_W_M2,
        "metabolic_w":           METABOLIC_WATT,
        "latent_correction":     LATENT_CORRECTION,
        "cache_expiry_seconds":  CACHE_EXPIRY_SECONDS,
        "ashrae_default_setpoint": 22.0,
        "ghost_setpoint_delta":    4.0,
    }