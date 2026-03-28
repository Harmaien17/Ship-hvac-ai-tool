import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from schemas import (
    CabinTelemetry, HVACDecision, FleetSummary,
    WasteHeatInput, WasteHeatResult, DrawingParseResult,
)
from hvac_engine import (
    calculate_optimized_load, calculate_fleet_summary,
    update_weather_cache, get_cached_weather,
    GHOST_COOLING_FRACTION, U_HULL_INSULATED, U_HULL_BARE,
    ENGINE_RADIANT_W_M2, THERMAL_LAG_W_M2,
    METABOLIC_W_PER_PERSON, LATENT_CORRECTION, CACHE_EXPIRY_SECONDS,
)
from weather import (
    fetch_current_weather, 
    fetch_and_save_14day_forecast,  # FIXED: Matches your weather.py logic
    get_forecast_summary_for_chart, 
    get_temp_for_hours_ahead, 
    get_cache_age_hours,
    load_forecast_cache,
)
from asset_defence import (
    run_asset_defence_checks,       # FIXED: Matches your asset_defence.py
    calculate_dew_point,
    MOLD_RH_THRESHOLD,
)
from waste_heat import calculate_waste_heat_recovery
from autocad_parser import parse_ship_drawing_pdf, ask_mar_chat

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mar_hvac.api")

OW_KEY = os.getenv("OPENWEATHER_API_KEY", "")
_last_decisions: dict[str, dict] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MAR-HVAC AI starting up...")
    yield
    logger.info("MAR-HVAC AI shutting down.")

app = FastAPI(
    title="MAR-HVAC AI",
    description="Marine Heat Load Optimisation Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _resolve_external_temp(lat: float, lon: float) -> Optional[float]:
    live = fetch_current_weather(lat, lon)
    if live:
        update_weather_cache(live["temp"], live["humidity"], live["solar"])
        return live["temp"]
    cache, status = get_cached_weather()
    if cache and status == "cache":
        return cache.temperature
    fc_temp = get_temp_for_hours_ahead(0)
    return fc_temp

@app.get("/api/v1/health")
def health():
    cache, status = get_cached_weather()
    return {"status": "online", "weather_cache": status, "api_key": bool(OW_KEY)}

@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry, lat: float = 19.0760, lon: float = 72.8777):
    if telemetry.external_temp is None:
        resolved = _resolve_external_temp(lat, lon)
        if resolved is not None:
            telemetry = telemetry.model_copy(update={"external_temp": resolved})

    # Run Asset Defence Checks
    asset = run_asset_defence_checks(
        cabin_id=telemetry.cabin_id,
        internal_temp=telemetry.internal_temp,
        internal_rh=telemetry.internal_humidity,
        external_temp=telemetry.external_temp,
        target_temp=telemetry.target_temp,
        market_segment=telemetry.market_segment
    )

    try:
        decision = calculate_optimized_load(telemetry)
        
        # Merge Asset Defence logs and warnings into the main decision
        decision.decision_log.extend(asset.log_lines)
        for w in asset.warnings:
            if w not in decision.warnings:
                decision.warnings.append(w)
        
        decision.dew_point = asset.dew_point_c
        _last_decisions[telemetry.cabin_id] = decision.model_dump()
        
        return decision
    except Exception as e:
        logger.exception(f"Engine error: {e}")
        raise HTTPException(500, f"Engine error: {e}")

@app.get("/api/v1/weather/forecast")
def forecast_save(lat: float = 19.0760, lon: float = 72.8777):
    """Week 3 — Fetch and save 14-day Starlink forecast buffer."""
    success = fetch_and_save_14day_forecast(lat, lon)
    if success:
        return {"success": True, "cache_age_h": get_cache_age_hours()}
    return {"success": False, "message": "Fetch failed."}

@app.post("/api/v1/waste-heat", response_model=WasteHeatResult)
def waste_heat(inp: WasteHeatInput):
    return calculate_waste_heat_recovery(inp)

@app.get("/api/v1/constants")
def constants():
    return {
        "ghost_cooling_fraction": GHOST_COOLING_FRACTION,
        "u_hull_insulated": U_HULL_INSULATED,
        "metabolic_w_per_person": METABOLIC_W_PER_PERSON,
        "mold_thresholds": MOLD_RH_THRESHOLD,
    }