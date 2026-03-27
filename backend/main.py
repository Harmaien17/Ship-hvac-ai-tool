"""
MAR-HVAC AI — FastAPI Backend
backend/main.py

UPDATED: Week 3 + Week 4

Run with:
  cd backend
  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Then open: http://localhost:8000/docs

Endpoints:
  GET  /api/v1/health                  — System health + cache status
  POST /api/v1/optimize                — Single cabin AI optimisation (Week 3+4)
  POST /api/v1/optimize/fleet          — Multi-cabin fleet optimisation
  GET  /api/v1/weather/update          — Refresh 1-hour weather cache
  GET  /api/v1/weather/forecast        — Fetch + save 7-day forecast buffer (Week 3)
  GET  /api/v1/weather/forecast/chart  — Load saved forecast for dashboard chart
  GET  /api/v1/asset-defence/status    — Check asset defence for one cabin (Week 4)
  GET  /api/v1/constants               — Engine constants for dashboard
"""

import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
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
# Week 3 — weather module
from weather import (
    fetch_current_weather,
    fetch_and_save_7day_forecast,
    load_forecast_cache,
    get_forecast_summary_for_chart,
    get_temp_for_hours_ahead,
    get_cache_age_hours,
)
# Week 4 — asset defence module
from asset_defence import (
    run_asset_defence_checks,
    calculate_dew_point,
    get_high_humidity_duration_minutes,
    MOLD_RH_THRESHOLD,
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
# STARTUP / SHUTDOWN
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MAR-HVAC AI backend starting up...")
    if not OPENWEATHER_API_KEY:
        logger.warning("OPENWEATHER_API_KEY not set — all weather will use fail-safe mode.")
    # Check if we have a saved forecast buffer
    cache_age = get_cache_age_hours()
    if cache_age is not None:
        logger.info(f"Forecast buffer found — {cache_age:.1f}h old.")
    else:
        logger.warning("No forecast buffer found. Call /api/v1/weather/forecast to pre-fetch.")
    yield
    logger.info("MAR-HVAC AI backend shutting down.")


# ─────────────────────────────────────────────────────────────
# APP INSTANCE
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="MAR-HVAC AI",
    description=(
        "Intelligent Heat Load Optimisation for Marine Vessels. "
        "Ghost Cooling Protocol. Asset Defence (Corrosion + Mold). "
        "7-Day Starlink Forecast Buffer. IMO 2030 Compliant."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Streamlit on AJIJ's laptop (same LAN)
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# INTERNAL WEATHER HELPER
# ─────────────────────────────────────────────────────────────

def _get_external_temp(lat: float, lon: float) -> Optional[float]:
    """
    Full fail-safe chain for resolving external temperature:
      1. Try live OpenWeather API
      2. Try 1-hour in-memory cache (hvac_engine)
      3. Try 7-day saved forecast (weather.py)
      4. Return None -> hvac_engine falls back to DHT22 + 5C

    Returns temperature in Celsius or None.
    """
    # Step 1: Live API
    live = fetch_current_weather(lat, lon)
    if live:
        update_weather_cache(live["temp"], live["humidity"], live["solar"])
        return live["temp"]

    # Step 2: 1-hour in-memory cache
    cache, status = get_cached_weather()
    if cache and status == "cache":
        logger.info(f"Using 1hr cache: {cache.temperature}C")
        return cache.temperature

    # Step 3: 7-day forecast buffer (the Starlink offline fallback)
    forecast_temp = get_temp_for_hours_ahead(0)
    if forecast_temp is not None:
        logger.info(f"Using 7-day forecast buffer: {forecast_temp}C")
        return forecast_temp

    # Step 4: Give up — hvac_engine will use DHT22 + 5C
    logger.warning("All weather sources exhausted — engine will use DHT22 fallback.")
    return None


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/health")
def health_check():
    """
    System health check.
    Shows API key status, weather cache, and forecast buffer age.
    Always call this first to confirm the server is running.
    """
    cache, status = get_cached_weather()
    cache_age = round(time.time() - cache.timestamp, 1) if cache else None
    forecast_age = get_cache_age_hours()

    return {
        "status":             "online",
        "version":            "1.0.0",
        "api_key_configured": bool(OPENWEATHER_API_KEY),
        "weather_cache": {
            "status":      status,
            "age_seconds": cache_age,
            "source":      cache.source if cache else None,
            "temp_c":      cache.temperature if cache else None,
        },
        "forecast_buffer": {
            "available":   forecast_age is not None,
            "age_hours":   forecast_age,
            "max_age_hours": 168,
        },
        "timestamp": time.time(),
    }


@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize_single_cabin(
    telemetry: CabinTelemetry,
    lat: float = Query(default=19.0760, description="Vessel latitude (GPS)"),
    lon: float = Query(default=72.8777, description="Vessel longitude (GPS)"),
):
    """
    Optimise HVAC load for one cabin.

    Week 3: Uses full fail-safe weather chain (API -> cache -> forecast -> DHT22).
    Week 4: Runs asset defence checks (corrosion/mold) before AI decision.

    Test body (paste in /docs):
    {
      "cabin_id": "CABIN-A3",
      "occupancy": false,
      "internal_temp": 28.5,
      "internal_humidity": 72.0,
      "direct_sunlight": true,
      "heat_soaked_hull": true,
      "engine_adjacent": false,
      "cabin_side": "starboard",
      "target_temp": 22.0,
      "cabin_area_m2": 20.0,
      "market_segment": "cargo"
    }
    """
    logger.info(f"Optimize: {telemetry.cabin_id} | occupied={telemetry.occupancy} | segment={telemetry.market_segment}")

    # Week 3: Resolve external temperature using full fail-safe chain
    if telemetry.external_temp is None:
        resolved_temp = _get_external_temp(lat, lon)
        if resolved_temp is not None:
            telemetry = telemetry.model_copy(update={"external_temp": resolved_temp})
        # If None, hvac_engine handles DHT22 fallback internally

    # Week 4: Run asset defence checks first
    # These checks influence the mode selection inside hvac_engine
    asset_result = run_asset_defence_checks(
        cabin_id        = telemetry.cabin_id,
        internal_temp   = telemetry.internal_temp,
        internal_rh     = telemetry.internal_humidity,
        market_segment  = telemetry.market_segment,
        is_medicine_room= False,   # Can be made a query param later
    )

    # Log the asset defence checks into the decision
    # The engine will also do its own dew point check — they will agree
    if asset_result.warnings:
        for w in asset_result.warnings:
            logger.warning(f"[ASSET] {telemetry.cabin_id}: {w}")

    try:
        decision = calculate_optimized_load(telemetry)
    except Exception as e:
        logger.exception(f"Engine error — {telemetry.cabin_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Engine error: {e}")

    # Inject asset defence log lines into the decision log
    # This way the dashboard shows both heat load AND asset defence in one log
    if asset_result.log_lines:
        decision.decision_log.extend(asset_result.log_lines)

    # Merge any new warnings from asset defence
    for w in asset_result.warnings:
        if w not in decision.warnings:
            decision.warnings.append(w)

    # Store dew point from asset defence (more authoritative calculation)
    if decision.dew_point is None:
        decision.dew_point = asset_result.dew_point_c

    logger.info(
        f"Result: {decision.cabin_id} | {decision.mode.value} | "
        f"{decision.optimized_load_kw:.3f} kW | saved {decision.energy_saved_percent:.1f}%"
    )
    return decision


@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def optimize_fleet(
    cabin_list: list[CabinTelemetry],
    lat: float = Query(default=19.0760),
    lon: float = Query(default=72.8777),
):
    """
    Optimise HVAC for an entire fleet. Weather fetched once, shared across all cabins.
    """
    if not cabin_list:
        raise HTTPException(status_code=422, detail="cabin_list cannot be empty.")
    if len(cabin_list) > 500:
        raise HTTPException(status_code=422, detail="Max 500 cabins per request.")

    logger.info(f"Fleet: {len(cabin_list)} cabins")

    # Resolve weather once for all cabins
    resolved_temp = _get_external_temp(lat, lon)
    if resolved_temp is not None:
        cabin_list = [
            c.model_copy(update={"external_temp": resolved_temp})
            if c.external_temp is None else c
            for c in cabin_list
        ]

    try:
        summary = calculate_fleet_summary(cabin_list)
    except Exception as e:
        logger.exception(f"Fleet error: {e}")
        raise HTTPException(status_code=500, detail=f"Fleet error: {e}")

    logger.info(
        f"Fleet: {summary.total_load_kw:.2f} kW | "
        f"savings {summary.fleet_savings_percent:.1f}% | "
        f"ghost {summary.ghost_cooling_cabins}/{summary.total_cabins}"
    )
    return summary


@app.get("/api/v1/weather/update")
def weather_update(
    lat: float = Query(default=19.0760),
    lon: float = Query(default=72.8777),
):
    """
    Manually refresh the 1-hour weather cache.
    Call from the Streamlit 'Refresh Weather' button.
    """
    live = fetch_current_weather(lat, lon)
    if live:
        update_weather_cache(live["temp"], live["humidity"], live["solar"])
        return {
            "success":    True,
            "temp_c":     live["temp"],
            "humidity":   live["humidity"],
            "cached_at":  time.time(),
            "source":     "openweather_api",
        }
    cache, status = get_cached_weather()
    return {
        "success":       False,
        "message":       "Live fetch failed. Check API key or internet connection.",
        "cache_status":  status,
        "fallback_temp": cache.temperature if cache else None,
    }


@app.get("/api/v1/weather/forecast")
def weather_forecast_fetch(
    lat: float = Query(default=19.0760, description="Vessel latitude"),
    lon: float = Query(default=72.8777, description="Vessel longitude"),
):
    """
    WEEK 3 — Fetch 5-day forecast from OpenWeather and save as 7-day buffer.

    Call this whenever you have a good internet connection (in port / coastal).
    The saved data becomes the offline fallback when Starlink drops at sea.

    After calling this once, the system can work without internet for up to 7 days.
    """
    success = fetch_and_save_7day_forecast(lat, lon)
    if success:
        cache = load_forecast_cache()
        return {
            "success":      True,
            "points_saved": cache["point_count"] if cache else 0,
            "cache_age_h":  get_cache_age_hours(),
            "message":      "7-day forecast buffer saved. System can now work offline.",
        }
    return {
        "success":   False,
        "message":   "Forecast fetch failed. Check internet connection and API key.",
        "fallback":  "System will use DHT22 sensor as fallback.",
    }


@app.get("/api/v1/weather/forecast/chart")
def weather_forecast_chart(
    lat: float = Query(default=19.0760),
    lon: float = Query(default=72.8777),
):
    """
    Return forecast data for the Streamlit Plotly chart.
    Uses saved buffer first (offline-safe), falls back to live API if buffer empty.
    """
    # Try saved buffer first (works offline)
    points = get_forecast_summary_for_chart()

    if not points:
        # Try live API if buffer is empty
        live_points = []
        try:
            resp = requests.get(
                f"{OW_BASE_URL}/forecast",
                params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
                timeout=8
            )
            resp.raise_for_status()
            items = resp.json().get("list", [])
            live_points = [
                {"ts": i["dt"], "temp": i["main"]["temp"],
                 "humidity": i["main"]["humidity"], "description": i["weather"][0]["main"]}
                for i in items
            ]
        except Exception:
            pass
        points = live_points

    return {
        "points":     points,
        "count":      len(points),
        "source":     "saved_buffer" if get_cache_age_hours() else "live_api",
        "cache_age_h": get_cache_age_hours(),
    }


@app.get("/api/v1/asset-defence/status")
def asset_defence_status(
    cabin_id        : str   = Query(default="CABIN-A1"),
    internal_temp   : float = Query(default=26.0),
    internal_rh     : float = Query(default=65.0),
    market_segment  : str   = Query(default="cargo"),
    is_medicine_room: bool  = Query(default=False),
):
    """
    WEEK 4 — Check asset defence status for a single cabin.

    Use this endpoint to check if a specific cabin has:
    - Corrosion risk (temp near dew point)
    - Mold risk (humidity too high for too long)
    - Hospital compliance violations

    Returns the full AssetDefenceResult as JSON.
    """
    result = run_asset_defence_checks(
        cabin_id         = cabin_id,
        internal_temp    = internal_temp,
        internal_rh      = internal_rh,
        market_segment   = market_segment,
        is_medicine_room = is_medicine_room,
    )
    return {
        "cabin_id":             cabin_id,
        "dew_point_c":          result.dew_point_c,
        "corrosion_risk":       result.corrosion_risk,
        "corrosion_severity":   result.corrosion_severity,
        "mold_risk":            result.mold_risk,
        "high_humidity_minutes": result.high_humidity_minutes,
        "mold_threshold_rh":    result.mold_threshold_rh,
        "hospital_mode_active": result.hospital_mode_active,
        "hospital_violations":  result.hospital_violations,
        "recommended_action":   result.recommended_action,
        "recommended_fan_speed": result.recommended_fan_speed,
        "warnings":             result.warnings,
        "log":                  result.log_lines,
    }


@app.get("/api/v1/constants")
def get_constants():
    """Engine constants for display in the Streamlit dashboard."""
    return {
        "ghost_cooling_fraction": GHOST_COOLING_FRACTION,
        "u_hull_insulated":       U_HULL_INSULATED,
        "u_hull_bare":            U_HULL_BARE,
        "engine_radiant_w_m2":   ENGINE_RADIANT_W_M2,
        "thermal_lag_w_m2":      THERMAL_LAG_W_M2,
        "metabolic_w":           METABOLIC_WATT,
        "latent_correction":     LATENT_CORRECTION,
        "cache_expiry_seconds":  CACHE_EXPIRY_SECONDS,
        "ashrae_setpoint":       22.0,
        "ghost_setpoint_delta":  4.0,
        "mold_thresholds":       MOLD_RH_THRESHOLD,
    }