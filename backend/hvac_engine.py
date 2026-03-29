import math
import logging
from typing import List

# ─────────────────────────────────────────────────────────────
# IMPORTANT FIX: FleetSummary is now imported here
# ─────────────────────────────────────────────────────────────
from backend.schemas import CabinTelemetry, HVACDecision, HeatLoadBreakdown, HVACMode, FleetSummary

logger = logging.getLogger("mar_hvac.engine")

# ─────────────────────────────────────────────────────────────
# CONSTANTS: Thermodynamic Engine & Economics
# ─────────────────────────────────────────────────────────────
U_VALUE_HULL = 0.5       # W/m2K
U_VALUE_WINDOW = 2.8     # W/m2K
SHGC_WINDOW = 0.6        # Solar Heat Gain Coefficient
METABOLIC_RATE = 115.0   # Watts per person (active seafarer)
LATENT_HEAT_VAPOR = 2260 # kJ/kg
AIR_DENSITY = 1.225      # kg/m3
SPECIFIC_HEAT_AIR = 1.006 # kJ/kgK

# ROI Configuration for GP Pune Pitch Target (12-18 Lakhs)
INR_PER_KWH = 15.0       # Average commercial/marine generator cost per kWh in ₹
CO2_KG_PER_KWH = 0.68    # Standard marine diesel emissions factor
SAILING_DAYS_YR = 300    # Active operational days per year


def calculate_optimized_load(telemetry: CabinTelemetry) -> HVACDecision:
    """Core Edge-AI Logic: Calculates the 11-point thermal load and applies occupancy optimizations."""
    log = [f"=== MAR-HVAC AI — Cabin {telemetry.cabin_id} ==="]
    warnings = []
    
    # 1. Fallback for Failsafe Mode (If weather API is totally down)
    ext_temp = telemetry.external_temp if telemetry.external_temp is not None else 32.0
    solar_irr = telemetry.solar_irradiance if telemetry.solar_irradiance is not None else 400.0
    
    delta_t = ext_temp - telemetry.internal_temp
    if delta_t < 0: delta_t = 0 # Heating is handled separately; focus is cooling load
    
    # ─────────────────────────────────────────────────────────────
    # THE 11-VARIABLE THERMODYNAMIC MATH
    # ─────────────────────────────────────────────────────────────
    # V1: Transmission (Hull/Walls)
    q_transmission = telemetry.cabin_area_m2 * U_VALUE_HULL * delta_t
    
    # V2: Solar (Windows)
    q_solar = telemetry.window_area_m2 * SHGC_WINDOW * solar_irr if telemetry.direct_sunlight else 0.0
    
    # V3: Engine Radiant Heat
    q_engine = 500.0 if telemetry.engine_adjacent else 0.0
    
    # V4: Thermal Lag (Heat-soaked hull from afternoon sun)
    q_lag = (q_transmission * 0.15) if telemetry.heat_soaked_hull else 0.0
    
    # V5: Latent Heat (Humidity extraction)
    humidity_excess = max(0, telemetry.internal_humidity - 50.0)
    q_latent = humidity_excess * 10.0 * telemetry.cabin_area_m2
    
    # V6: Metabolic (Occupants breathing/moving)
    occupants = telemetry.occupant_count if telemetry.occupancy else 0
    q_metabolic = occupants * METABOLIC_RATE
    
    # V7: Equipment (Laptops, lights, sensors)
    q_equipment = telemetry.equipment_wattage if telemetry.occupancy else (telemetry.equipment_wattage * 0.1)
    
    # V8: Fenestration/Infiltration (Door drafts)
    q_fenestration = 0.05 * q_transmission
    
    # V9 & V10: Ceiling and Floor Conduction
    q_ceiling = telemetry.ceiling_area_exposed_m2 * U_VALUE_HULL * delta_t * 0.8
    q_floor = telemetry.floor_area_exposed_m2 * U_VALUE_HULL * delta_t * 0.5
    
    # V11: Total Raw Load
    q_total_raw_w = (q_transmission + q_solar + q_engine + q_lag + 
                     q_latent + q_metabolic + q_equipment + 
                     q_fenestration + q_ceiling + q_floor)
    
    baseline_load_kw = q_total_raw_w / 1000.0
    
    # ─────────────────────────────────────────────────────────────
    # AI DECISION TREE & "CHATBOT" LOG GENERATION
    # ─────────────────────────────────────────────────────────────
    optimized_load_kw = baseline_load_kw
    actual_setpoint = telemetry.target_temp
    mode = HVACMode.FULL_COOLING
    
    if not telemetry.occupancy:
        mode = HVACMode.STANDBY
        optimized_load_kw *= 0.30 # 70% energy reduction for empty cabins
        actual_setpoint = 26.0
        log.append("Occupancy Sensor: Empty. Triggering STANDBY mode.")
        log.append(f"Setpoint allowed to drift safely to {actual_setpoint}°C to save fuel.")
    elif ext_temp < telemetry.target_temp:
        mode = HVACMode.REDUCED_COOLING
        optimized_load_kw *= 0.50
        log.append("External weather is optimal. Integrating outside air to reduce compressor load.")
    else:
        log.append(f"Occupancy Sensor: Active ({occupants} pax). Full precision cooling engaged.")

    if telemetry.internal_humidity > 75.0:
        mode = HVACMode.MOLD_ALERT
        optimized_load_kw += 0.5 # Extra power allocated for dehumidification
        warnings.append("WARNING: Mold risk detected. Engaging high-power dehumidification.")
        log.append("Executing latent heat extraction sequence to protect assets.")

    optimized_load_kw = max(0.1, optimized_load_kw) # Prevent impossible zero values
    
    # ─────────────────────────────────────────────────────────────
    # ROI & CO2 CALCULATOR (Outputting to ₹ for Dashboard)
    # ─────────────────────────────────────────────────────────────
    energy_saved_kw = baseline_load_kw - optimized_load_kw
    if energy_saved_kw < 0: energy_saved_kw = 0
    
    energy_saved_percent = (energy_saved_kw / baseline_load_kw * 100) if baseline_load_kw > 0 else 0
    
    money_saved_hr = energy_saved_kw * INR_PER_KWH
    co2_saved_hr = energy_saved_kw * CO2_KG_PER_KWH
    annual_roi = money_saved_hr * 24 * SAILING_DAYS_YR
    
    log.append(f"Calculation complete: Reduced energy waste by {energy_saved_percent:.1f}%.")

    # Construct Response
    breakdown = HeatLoadBreakdown(
        q_transmission=q_transmission, q_solar=q_solar, q_engine_radiant=q_engine,
        q_thermal_lag=q_lag, q_latent=q_latent, q_metabolic=q_metabolic,
        q_equipment=q_equipment, q_fenestration=q_fenestration,
        q_ceiling=q_ceiling, q_floor_conduction=q_floor,
        q_total_raw=q_total_raw_w, heating_load_kw=0.0
    )

    return HVACDecision(
        cabin_id=telemetry.cabin_id,
        mode=mode,
        optimized_load_kw=round(optimized_load_kw, 2),
        setpoint_actual=actual_setpoint,
        energy_saved_percent=round(energy_saved_percent, 1),
        breakdown=breakdown,
        decision_log=log,
        warnings=warnings,
        weather_source="cache" if telemetry.external_temp is None else "live",
        dew_point=telemetry.internal_temp - ((100 - telemetry.internal_humidity)/5), # Approximation
        money_saved_hr_inr=round(money_saved_hr, 2),
        co2_saved_hr_kg=round(co2_saved_hr, 2),
        annual_roi_inr=round(annual_roi, 2)
    )

def calculate_fleet_summary(cabin_list: List[CabinTelemetry]) -> FleetSummary:
    """Aggregates all cabin data to create ship-wide ROI and CO2 metrics."""
    total_load = 0.0
    total_savings = 0.0
    total_co2 = 0.0
    occupied_count = 0
    decisions = []

    for cabin in cabin_list:
        decision = calculate_optimized_load(cabin)
        decisions.append(decision)
        total_load += decision.optimized_load_kw
        total_savings += decision.annual_roi_inr
        
        # Scale CO2 to Annual Metric Tons
        annual_co2_kg = decision.co2_saved_hr_kg * 24 * SAILING_DAYS_YR
        total_co2 += (annual_co2_kg / 1000.0) 
        
        if cabin.occupancy:
            occupied_count += 1

    return FleetSummary(
        total_cabins=len(cabin_list),
        occupied_cabins=occupied_count,
        total_load_kw=round(total_load, 2),
        total_annual_savings_inr=round(total_savings, 2),
        total_annual_co2_tons=round(total_co2, 2),
        cabins=decisions
    )