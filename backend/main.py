import os, logging
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from schemas import CabinTelemetry, HVACDecision, FleetSummary, WasteHeatInput, WasteHeatResult
from hvac_engine import calculate_optimized_load, calculate_fleet_summary
from asset_defence import run_asset_defence_checks
from autocad_parser import parse_ship_drawing_pdf

app = FastAPI(title="MAR-HVAC AI", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/v1/health")
def health(): return {"status": "online"}

@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry):
    asset = run_asset_defence_checks(telemetry.cabin_id, telemetry.internal_temp, telemetry.internal_humidity, 35.0, telemetry.target_temp, telemetry.market_segment)
    try:
        decision = calculate_optimized_load(telemetry)
        decision.decision_log.extend(asset.log_lines); decision.warnings.extend(asset.warnings); decision.dew_point = asset.dew_point_c
        return decision
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def fleet(cabin_list: list[CabinTelemetry]):
    return calculate_fleet_summary(cabin_list)

@app.post("/api/v1/parse-drawing")
async def parse_drawing(file: UploadFile = File(...)):
    return parse_ship_drawing_pdf(await file.read())