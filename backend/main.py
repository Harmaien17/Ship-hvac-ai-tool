import os, logging
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from schemas import CabinTelemetry, HVACDecision, FleetSummary, WasteHeatInput, WasteHeatResult
from hvac_engine import calculate_optimized_load, calculate_fleet_summary
from asset_defence import run_asset_defence_checks
# REMOVED: autocad_parser import to save RAM

app = FastAPI(title="MAR-HVAC AI", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/v1/health")
def health(): return {"status": "online"}

@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry):
    # Running Asset Defence checks (Dew Point, Mold, Hospital Mode)
    asset = run_asset_defence_checks(
        telemetry.cabin_id, 
        telemetry.internal_temp, 
        telemetry.internal_humidity, 
        35.0, 
        telemetry.target_temp, 
        telemetry.market_segment
    )
    try:
        # Calculating thermodynamic load and ROI
        decision = calculate_optimized_load(telemetry)
        decision.decision_log.extend(asset.log_lines)
        decision.warnings.extend(asset.warnings)
        decision.dew_point = asset.dew_point_c
        return decision
    except Exception as e: 
        raise HTTPException(500, str(e))

@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def fleet(cabin_list: list[CabinTelemetry]):
    # Aggregated ship-wide efficiency tracking
    return calculate_fleet_summary(cabin_list)

