import math
import logging
from typing import List, Optional
from backend.schemas import CabinTelemetry, HVACDecision, HeatLoadBreakdown, HVACMode, FleetSummary

logger = logging.getLogger("mar_hvac.engine")

# ─────────────────────────────────────────────────────────────
# CONSTANTS: Thermodynamic Engine (UPDATED TO FORMULA SHEET)
# ─────────────────────────────────────────────────────────────
U_VALUE_WALL = 1.5       # W/m2K
U_VALUE_WINDOW = 5.8     # W/m2K
WINDOW_SGHF = 700.0      # Solar Heat Gain Factor
WINDOW_SC = 0.8          # Shading Coefficient
PEOPLE_SENSIBLE = 75.0   # Watts per person
PEOPLE_LATENT = 55.0     # Watts per person
LPS_PER_PERSON = 10.0    # Liters per second of fresh air (Standard assumption)
AIR_DENSITY_CP = 1.2     # Constant for 1.2 multiplier in formula

# ROI Configuration for Idea Forge Pitch
INR_PER_KWH = 15.0       # Marine generator cost in ₹
CO2_KG_PER_KWH = 0.68    # Diesel emissions factor
SAILING_DAYS_YR = 300    # Active operational days

def calculate_optimized_load(telemetry: CabinTelemetry, blueprint_total: Optional[float] = None) -> HVACDecision:
    """Core Edge-AI Logic: Calculates 11-point thermal load with Blueprint ROI verification."""
    log = [f"=== MAR-HVAC AI — Cabin {telemetry.cabin_id} ==="]
    warnings = []
    
    # 1. Environmental Fallbacks
    ext_temp = telemetry.external_temp if telemetry.external_temp is not None else 32.0
    delta_t = max(0, ext_temp - telemetry.target_temp)
    
    # ─────────────────────────────────────────────────────────────
    # THE 11-VARIABLE THERMODYNAMIC MATH (FORMULA SHEET INTEGRATION)
    # ─────────────────────────────────────────────────────────────
    
    # V1, V9, V10: Transmission Heat Load (Sensible)
    q_wall = telemetry.cabin_area_m2 * U_VALUE_WALL * delta_t
    q_ceiling = telemetry.ceiling_area_exposed_m2 * U_VALUE_WALL * delta_t
    q_floor = telemetry.floor_area_exposed_m2 * U_VALUE_WALL * delta_t
    q_transmission = q_wall + q_ceiling + q_floor
    
    # V2 & V8: Window Load (Solar + Conduction)
    total_window_area = telemetry.window_area_m2 * telemetry.window_count
    q_fenestration = total_window_area * U_VALUE_WINDOW * delta_t
    q_solar = total_window_area * WINDOW_SGHF * WINDOW_SC if telemetry.direct_sunlight else 0.0
    
    # V6 & V5 (Part A): People Load (Sensible & Latent)
    occupants = telemetry.occupant_count if telemetry.occupancy else 0
    q_people_sensible = occupants * PEOPLE_SENSIBLE
    q_people_latent = occupants * PEOPLE_LATENT
    
    # V7: Equipment Load
    q_equipment = telemetry.equipment_wattage if telemetry.occupancy else (telemetry.equipment_wattage * 0.1)

    # V5 (Part B): Ventilation Load (Sensible & Latent)
    # Step 1: Airflow in m3/s (Assuming 40% fresh air as per rules)
    airflow_m3_s = (LPS_PER_PERSON * occupants * 0.40) / 1000.0
    
    # Step 2: Sensible Load
    q_vent_sensible = AIR_DENSITY_CP * airflow_m3_s * delta_t * 1000 # Convert to Watts
    
    # Step 3: Latent Load (Using your approx psychrometric difference of 75 kJ/kg)
    enthalpy_diff = 75.0 
    q_vent_latent = AIR_DENSITY_CP * airflow_m3_s * enthalpy_diff * 1000 # Convert to Watts

    # V3 & V4: Additional Variables (Engine Radiant & Thermal Lag)
    q_engine = 500.0 if telemetry.engine_adjacent else 0.0
    q_lag = (q_transmission * 0.15) if telemetry.heat_soaked_hull else 0.0

    # Variable 11 Check: Total Heat Load
    total_sensible = q_transmission + q_fenestration + q_solar + q_people_sensible + q_vent_sensible + q_equipment + q_engine + q_lag
    total_latent = q_people_latent + q_vent_latent
    q_total_raw_w = total_sensible + total_latent
    
    # ─────────────────────────────────────────────────────────────
    # ROI INTEGRATION: Design vs AI (BUG FIXES APPLIED)
    # ─────────────────────────────────────────────────────────────
    
    # PITCH SAFEGUARD: The Factor-of-100 decimal fix
    # If the parser accidentally returns 60.6W instead of 6060W, this autocorrects it.
    actual_blueprint_w = blueprint_total
    if actual_blueprint_w and actual_blueprint_w < 100:
        actual_blueprint_w *= 100 
        log.append("⚠️ Watchdog: Auto-corrected volumetric scaling parser issue.")

    if actual_blueprint_w and actual_blueprint_w > 0:
        baseline_load_kw = actual_blueprint_w / 1000.0
        # AI uses the Company File as the absolute truth starting point
        ai_starting_load_kw = baseline_load_kw 
        log.append(f"ROI BASELINE: Using Official Blueprint ({baseline_load_kw:.2f}kW).")
    else:
        baseline_load_kw = q_total_raw_w / 1000.0
        # AI uses the thermodynamic formulas if no file exists
        ai_starting_load_kw = baseline_load_kw
        log.append(f"ROI BASELINE: Using sensor-calculated baseline ({baseline_load_kw:.2f}kW).")

    # ─────────────────────────────────────────────────────────────
    # AI DECISION LOGIC (Applying Savings to the True Baseline)
    # ─────────────────────────────────────────────────────────────
    optimized_load_kw = ai_starting_load_kw
    actual_setpoint = telemetry.target_temp
    mode = HVACMode.FULL_COOLING
    
    if not telemetry.occupancy:
        mode = HVACMode.MAINTENANCE_COOLING   # Ghost Cooling Protocol
        optimized_load_kw *= 0.30             # Cuts the base load drastically
        actual_setpoint = 26.0
        log.append("Occupancy Sensor: Empty. MAINTENANCE_COOLING (Ghost Cooling) engaged.")
    elif ext_temp < telemetry.target_temp:
        mode = HVACMode.REDUCED_COOLING
        optimized_load_kw *= 0.50
        log.append("Condition: Optimal weather. Peak-shaving engaged.")

    if telemetry.internal_humidity > 75.0:
        mode = HVACMode.MOLD_ALERT
        optimized_load_kw += 0.5
        warnings.append("WARNING: Mold risk detected.")

    optimized_load_kw = max(0.1, optimized_load_kw)
    
    # ─────────────────────────────────────────────────────────────
    # ECONOMICS & CARBON CREDITS
    # ─────────────────────────────────────────────────────────────
    energy_saved_kw = max(0, baseline_load_kw - optimized_load_kw)
    energy_saved_percent = (energy_saved_kw / baseline_load_kw * 100) if baseline_load_kw > 0 else 0
    money_saved_hr = energy_saved_kw * INR_PER_KWH
    co2_saved_hr = energy_saved_kw * CO2_KG_PER_KWH
    annual_roi = money_saved_hr * 24 * SAILING_DAYS_YR
    
    log.append(f"AI Efficiency Gain: {energy_saved_percent:.1f}%.")

    return HVACDecision(
        cabin_id=telemetry.cabin_id,
        mode=mode,
        optimized_load_kw=round(optimized_load_kw, 2),
        setpoint_actual=actual_setpoint,
        energy_saved_percent=round(energy_saved_percent, 1),
        breakdown=HeatLoadBreakdown(
            q_transmission=q_wall, q_solar=q_solar, q_engine_radiant=q_engine,
            q_thermal_lag=q_lag, q_latent=total_latent, q_metabolic=q_people_sensible,
            q_equipment=q_equipment, q_fenestration=q_fenestration,
            q_ceiling=q_ceiling, q_floor_conduction=q_floor,
            q_total_raw=q_total_raw_w
        ),
        decision_log=log,
        warnings=warnings,
        weather_source="live" if telemetry.external_temp else "cache",
        dew_point=telemetry.internal_temp - ((100 - telemetry.internal_humidity)/5),
        money_saved_hr_inr=round(money_saved_hr, 2),
        co2_saved_hr_kg=round(co2_saved_hr, 2),
        annual_roi_inr=round(annual_roi, 2)
    )

def calculate_fleet_summary(cabin_list: List[CabinTelemetry]) -> FleetSummary:
    """Aggregates ship-wide metrics for the fleet dashboard."""
    total_load, total_savings, total_co2, occupied_count = 0.0, 0.0, 0.0, 0
    decisions = []

    for cabin in cabin_list:
        decision = calculate_optimized_load(cabin)
        decisions.append(decision)
        total_load += decision.optimized_load_kw
        total_savings += decision.annual_roi_inr
        total_co2 += (decision.co2_saved_hr_kg * 24 * SAILING_DAYS_YR / 1000.0) 
        if cabin.occupancy: occupied_count += 1

    return FleetSummary(
        total_cabins=len(cabin_list), occupied_cabins=occupied_count,
        total_load_kw=round(total_load, 2), total_annual_savings_inr=round(total_savings, 2),
        total_annual_co2_tons=round(total_co2, 2), cabins=decisions
    )