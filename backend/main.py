import os, logging
import requests
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Standardized Absolute Imports
from backend.schemas import CabinTelemetry, HVACDecision, FleetSummary, WasteHeatInput, WasteHeatResult, WeatherCache
from backend.hvac_engine import calculate_optimized_load, calculate_fleet_summary
from backend.asset_defence import run_asset_defence_checks
from backend.waste_heat import calculate_waste_heat_recovery
from backend.weather import get_14_day_forecast, OPENWEATHER_API_KEY, get_cache_age_hours

app = FastAPI(title="MAR-HVAC AI", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────
# 1. HEALTH & STARLINK STATUS
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
def health():
    """System health and Starlink satellite connectivity check."""
    starlink_online = False
    if OPENWEATHER_API_KEY:
        try:
            # Quick ping to verify satellite/internet connectivity
            requests.get("https://api.openweathermap.org", timeout=1.5)
            starlink_online = True
        except:
            starlink_online = False

    return {
        "status": "online",
        "starlink_active": starlink_online,
        "cache_resilience": "active",
        "cache_age_hours": get_cache_age_hours(),
        "engine_version": "1.1.0"
    }

# ─────────────────────────────────────────────────────────────
# 2. WEATHER & FORECAST
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/forecast", response_model=WeatherCache)
def get_weather_forecast(lat: float = 19.07, lon: float = 72.87):
    """Provides the 14-day forecast for UI charts and AI prediction."""
    try:
        return get_14_day_forecast(lat, lon)
    except Exception as e:
        raise HTTPException(500, str(e))

# ─────────────────────────────────────────────────────────────
# 3. THERMODYNAMIC OPTIMIZATION ENGINE
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry):
    """Core 11-variable AI logic for a single cabin."""
    asset = run_asset_defence_checks(
        telemetry.cabin_id, 
        telemetry.internal_temp, 
        telemetry.internal_humidity, 
        35.0, 
        telemetry.target_temp, 
        telemetry.market_segment
    )
    try:
        decision = calculate_optimized_load(telemetry)
        decision.decision_log.extend(asset.log_lines)
        decision.warnings.extend(asset.warnings)
        decision.dew_point = asset.dew_point_c
        return decision
    except Exception as e: 
        raise HTTPException(500, str(e))

# ─────────────────────────────────────────────────────────────
# 4. FLEET SUMMARY & AGGREGATION
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def fleet(cabin_list: list[CabinTelemetry]):
    """Aggregated ship-wide efficiency and ROI tracking."""
    return calculate_fleet_summary(cabin_list)

# ─────────────────────────────────────────────────────────────
# 5. WASTE HEAT RECOVERY
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/waste-heat", response_model=WasteHeatResult)
def waste_heat(payload: WasteHeatInput):
    """Calculates green energy offsets from engine exhaust."""
    return calculate_waste_heat_recovery(payload)