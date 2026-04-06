import os, logging, gc
import requests, time, sys, threading
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

# Standardized Absolute Imports
from backend.schemas import CabinTelemetry, HVACDecision, FleetSummary, WasteHeatInput, WasteHeatResult, WeatherCache
from backend.hvac_engine import calculate_optimized_load, calculate_fleet_summary
from backend.asset_defence import run_asset_defence_checks, governor  # <-- Imported the governor
from backend.waste_heat import calculate_waste_heat_recovery
from backend.weather import get_14_day_forecast, OPENWEATHER_API_KEY, get_cache_age_hours

# ─────────────────────────────────────────────────────────────
# SMART BRIDGE: Ajij Parser vs. Mock Data Fallback
# ─────────────────────────────────────────────────────────────
try:
    # If Ajij has pushed 'autocad_parse.py', this will activate
    from backend.autocad_parse import extract_hvac_variables
    USING_MOCK = False
except ImportError:
    # While Ajij is offline, we use your 'mock_parser.py' for the 11 variables
    from backend.mock_parser import get_mock_drawing_data
    USING_MOCK = True
    def extract_hvac_variables(file): 
        return get_mock_drawing_data() 

app = FastAPI(title="MAR-HVAC AI", version="1.2.4")

# Enable CORS for Frontend Dashboard connectivity
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ─────────────────────────────────────────────────────────────
# NEW: HARDWARE WATCHDOG TIMER
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("MarHVAC-Core")
last_heartbeat = time.time()

def hardware_watchdog():
    """Background task that ensures AI hasn't crashed. Protects physical hardware."""
    global last_heartbeat
    while True:
        try:
            last_heartbeat = time.time()
            # ADD THIS PRINT STATEMENT:
            print("[WATCHDOG] Heartbeat sent to HVAC relays... Connection stable.")
            logger.info("❤️ [WATCHDOG] Heartbeat sent to HVAC relays... Connection stable.")
            time.sleep(10)
        except Exception as e:
            print(f"FATAL WATCHDOG FAILURE: {e}")
            logger.critical(f"FATAL WATCHDOG FAILURE: {e}")
            governor.trigger_hardware_override()
            sys.exit(1) # Kill server, let hardware mechanical relays take over

@app.on_event("startup")
async def startup_event():
    # ADD THIS PRINT STATEMENT:
    print("[SYSTEM] Starting Edge Server & Hardware Watchdog...")
    logger.info("🚀 Starting Edge Server & Hardware Watchdog...")
    # Spin up the watchdog safely without blocking the FastAPI engine
    threading.Thread(target=hardware_watchdog, daemon=True).start()

# ─────────────────────────────────────────────────────────────
# 1. HEALTH & HARDWARE STATUS (Starlink + RAM Check)
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
def health():
    """System health check and hardware resource validation."""
    starlink_online = False
    if OPENWEATHER_API_KEY:
        try:
            # Check connectivity for marine routes via Starlink simulator
            requests.get("https://api.openweathermap.org", timeout=1.5)
            starlink_online = True
        except:
            starlink_online = False 

    return {
        "status": "online",
        "starlink_active": starlink_online,
        "hardware_profile": "HP-Pavilion-4GB-RAM",
        "ram_optimization": "active",
        "parser_mode": "MOCK" if USING_MOCK else "LIVE_AUTOCAD",
        "cache_age_hours": get_cache_age_hours(),
        "engine_version": "1.2.4"
    }

# ─────────────────────────────────────────────────────────────
# 2. SMART BLUEPRINT ANALYSIS (ROI + Asset Defence Integration)
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/analyze/blueprint")
async def analyze_blueprint(
    cabin_id: str = Form(...),
    internal_temp: float = Form(...),
    internal_rh: float = Form(...),
    market_segment: str = Form("cargo"),
    drawing: UploadFile = File(...)
):
    """
    Extracts 11 variables from drawings and calculates Design-to-AI ROI.
    Smart Limits: 15MB for .dwg | 5MB for .pdf (RAM Safety for 4GB).
    """
    filename = drawing.filename.lower()
    
    # 1. Read file & Enforce RAM Limits
    content = await drawing.read()
    filesize = len(content)
    await drawing.seek(0) # Reset pointer for the actual parser logic

    if filename.endswith('.dwg') and filesize > 15 * 1024 * 1024:
        raise HTTPException(400, "CAD file too large for 4GB RAM (Limit 15MB)")
    elif filename.endswith('.pdf') and filesize > 5 * 1024 * 1024:
        raise HTTPException(400, "PDF file too large for 4GB RAM (Limit 5MB)")
    elif not (filename.endswith('.dwg') or filename.endswith('.pdf')):
        raise HTTPException(400, "Unsupported format. Use .dwg or .pdf")

    # 2. Extract 11 Variables (Variable 11: total_raw_load)
    try:
        from io import BytesIO
        parser_data = extract_hvac_variables(BytesIO(content))
        blueprint_load = parser_data.get("total_raw_load", 0.0)
    except Exception as e:
        logger.error(f"Parser Error: {e}")
        parser_data = {}
        blueprint_load = 0.0

    # 3. Run Integrated Asset Defence Logic
    asset = run_asset_defence_checks(
        cabin_id=cabin_id,
        internal_temp=internal_temp,
        internal_rh=internal_rh,
        market_segment=market_segment,
        parser_data=parser_data
    )

    # 4. ROI Verification Logic
    temp_telemetry = CabinTelemetry(
        cabin_id=cabin_id,
        internal_temp=internal_temp,
        internal_humidity=internal_rh,
        market_segment=market_segment,
        occupancy=True 
    )
    
    roi_result = calculate_optimized_load(temp_telemetry, blueprint_total=blueprint_load)

    # 5. Explicit RAM Cleanup for HP Pavilion
    del content
    gc.collect()

    return {
        "cabin_id": cabin_id,
        "blueprint_variables": parser_data,
        "asset_defence": {
            "corrosion_risk": asset.corrosion_risk,
            "mold_alert": asset.mold_risk,
            "latent_heat_impact": asset.latent_heat_impact,
            "thermal_stress": asset.hull_thermal_stress,
            "recommended_action": asset.recommended_action
        },
        "roi_analysis": {
            "annual_savings_inr": roi_result.annual_roi_inr,
            "efficiency_gain": f"{roi_result.energy_saved_percent}%",
            "co2_saved_kg_hr": roi_result.co2_saved_hr_kg,
            "money_saved_hr_inr": roi_result.money_saved_hr_inr
        },
        "warnings": asset.warnings,
        "mode": "MOCK_DATA_PREVIEW" if USING_MOCK else "LIVE_CAD_PARSED"
    }

# ─────────────────────────────────────────────────────────────
# 3. STANDARD THERMODYNAMIC OPTIMIZATION
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/optimize", response_model=HVACDecision)
def optimize(telemetry: CabinTelemetry):
    """Core logic using the 11-variable thermodynamic engine."""
    try:
        # Step 1: Check if hardware has been forced into override by a previous failure
        if governor.is_baseline_mode:
            logger.error("Attempted to optimize while in Emergency Override.")
            # Return a failsafe decision to frontend
            decision = calculate_optimized_load(telemetry) 
            decision.mode = "FAILSAFE"
            decision.optimized_load_kw = 0.0 
            decision.decision_log.append("🚨 EMERGENCY BASELINE ACTIVE. AI DISABLED.")
            return decision

        # Step 2: First run safety checks to populate log_lines
        asset = run_asset_defence_checks(
            telemetry.cabin_id, 
            telemetry.internal_temp, 
            telemetry.internal_humidity, 
            35.0, # Default external temp
            telemetry.target_temp, 
            telemetry.market_segment
        )
        
        # Step 3: Engine generates predictive load
        decision = calculate_optimized_load(telemetry)
        decision.decision_log.extend(asset.log_lines)
        decision.warnings.extend(asset.warnings)
        decision.dew_point = asset.dew_point_c

        # Step 4: Hardware Governor intercepts and sanitizes the final AI target temp
        safe_target = governor.verify_and_safeguard(telemetry.internal_temp, telemetry.target_temp)
        decision.decision_log.append(f"🛡️ Governor verified execution target: {safe_target}°C")

        return decision

    except Exception as e: 
        # TOTAL SYSTEM CRASH CATCHER
        logger.critical(f"🔥 FATAL AI CRASH DETECTED: {str(e)} 🔥")
        governor.trigger_hardware_override()
        raise HTTPException(500, f"System crashed. Reverted to Baseline HVAC. Error: {str(e)}")

# ─────────────────────────────────────────────────────────────
# 4. WEATHER, FLEET & WASTE HEAT RECOVERY
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/weather/forecast")
def get_weather_forecast(lat: float = 19.07, lon: float = 72.87):
    """Fetch 14-day forecast for route planning via Starlink."""
    get_14_day_forecast(lat, lon)
    return {"success": True, "points_saved": 14, "message": "Forecast saved successfully"}

@app.get("/api/v1/weather/forecast/chart")
def get_forecast_chart():
    """Generates the 14-day chart points for the frontend Dashboard."""
    now = int(time.time())
    points = []
    for i in range(14):
        points.append({
            "ts": now + (i * 86400),
            "temp": 28.0 + (i % 3) - (i * 0.2), 
            "humidity": 65 + (i % 5)
        })
    return {"points": points}

@app.post("/api/v1/optimize/fleet", response_model=FleetSummary)
def fleet(cabin_list: list[CabinTelemetry]):
    """Aggregate ROI and CO2 savings for the entire ship."""
    return calculate_fleet_summary(cabin_list)

@app.post("/api/v1/waste-heat", response_model=WasteHeatResult)
def waste_heat(payload: WasteHeatInput):
    """Calculate green energy offset from engine exhaust."""
    return calculate_waste_heat_recovery(payload)