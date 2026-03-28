"""
MAR-HVAC AI — FastAPI Backend
backend/main.py
"""

import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from schemas import (
    CabinTelemetry, HVACDecision, FleetSummary,
    WasteHeatInput, WasteHeatResult, DrawingParseResult,
)
from hvac_engine import (
    calculate_optimized_load, calculate_fleet_summary,
    update_weather_cache, get_cached_weather
)
from weather import (
    fetch_current_weather, 
    fetch_and_save_14day_forecast, 
    get_temp_for_hours_ahead, 
    get_cache_age_hours
)
from asset_defence import run_asset_defence_checks
from waste_heat import calculate_waste_heat_recovery
from autocad_parser import parse_ship_drawing_pdf, ask_mar_chat

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mar_hvac.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MAR-HVAC AI starting up...")
    yield
    logger.info("MAR-HVAC AI shutting down.")

app = FastAPI(title="MAR-HVAC AI", version="1.1.0", lifespan=lifespan)

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
    cache, _ = get_cached_weather()
    return cache.temperature if cache else get_temp_for_hours_ahead(0)

@app.get("/api/v1/health")
def health():
    return {"status": "online"}

@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry, lat: float = 19.0760, lon: float = 72.8777):
    if telemetry.external_temp is None:
        telemetry.external_temp = _resolve_external_temp(lat, lon)
    
    # Week 4 Asset Defence
    asset = run_asset_defence_checks(
        telemetry.cabin_id, telemetry.internal_temp, telemetry.internal_humidity,
        telemetry.external_temp, telemetry.target_temp, telemetry.market_segment
    )

    try:
        decision = calculate_optimized_load(telemetry)
        decision.decision_log.extend(asset.log_lines)
        decision.warnings.extend(asset.warnings)
        decision.dew_point = asset.dew_point_c
        return decision
    except Exception as e:
        logger.exception(f"Engine error: {e}")
        raise HTTPException(500, f"Engine error: {e}")

@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def fleet(cabin_list: list[CabinTelemetry]):
    """FIXED: Uses lowercase list for Python 3.12 compatibility"""
    return calculate_fleet_summary(cabin_list)

@app.get("/api/v1/weather/forecast")
def forecast_save(lat: float = 19.0760, lon: float = 72.8777):
    success = fetch_and_save_14day_forecast(lat, lon)
    return {"success": success, "cache_age_h": get_cache_age_hours()}

@app.post("/api/v1/waste-heat", response_model=WasteHeatResult)
def waste_heat(inp: WasteHeatInput):
    return calculate_waste_heat_recovery(inp)

@app.post("/api/v1/parse-drawing")
async def parse_drawing(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    return parse_ship_drawing_pdf(pdf_bytes)