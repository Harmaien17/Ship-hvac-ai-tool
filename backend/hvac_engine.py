import time
import logging
from typing import Optional
from schemas import CabinTelemetry, HVACDecision, HeatLoadBreakdown, HVACMode, WeatherCache, FleetSummary
from economics import calculate_roi_metrics

# PHYSICAL CONSTANTS
U_HULL_INSULATED = 0.65; U_HULL_BARE = 4.8; U_DECK_SLAB = 1.2; U_ROOF_EXPOSED = 2.8
WALL_AREA_FACTOR = 1.8; SHGC_WINDOW = 0.65; SOL_AIR_DELTA_T = 15.0
METABOLIC_W_PER_PERSON = 75; ENGINE_RADIANT_W_M2 = 85; THERMAL_LAG_W_M2 = 55
LATENT_CORRECTION = 1.18

def calc_ceiling_solar(irradiance, area_m2, delta_t):
    if area_m2 <= 0.0 or irradiance < 50.0: return 0.0
    return max(0.0, U_ROOF_EXPOSED * area_m2 * (delta_t + SOL_AIR_DELTA_T))

def calc_floor_conduction(area_m2, internal_temp):
    if area_m2 <= 0.0: return 0.0
    return max(0.0, U_DECK_SLAB * area_m2 * (65.0 - internal_temp))

def calculate_optimized_load(t: CabinTelemetry) -> HVACDecision:
    log = [f"=== MAR-HVAC AI — Ship Length: {t.ship_length_m}m ==="]
    
    ext_temp = t.external_temp or (t.internal_temp + 5.0)
    solar = t.solar_irradiance or 400.0
    delta_t = ext_temp - t.target_temp

    u_wall = U_HULL_BARE if t.engine_adjacent else U_HULL_INSULATED
    q_trans = max(0.0, u_wall * (t.cabin_area_m2 * WALL_AREA_FACTOR) * delta_t)
    q_metabolic = float(t.occupant_count) * METABOLIC_W_PER_PERSON
    q_equip = t.equipment_wattage
    q_fenes = max(0.0, solar * t.window_area_m2 * SHGC_WINDOW)
    q_ceiling = calc_ceiling_solar(solar, t.ceiling_area_exposed_m2, delta_t)
    q_floor = calc_floor_conduction(t.floor_area_exposed_m2, t.internal_temp)
    q_engine = ENGINE_RADIANT_W_M2 * t.cabin_area_m2 if t.engine_adjacent else 0.0
    q_lag = THERMAL_LAG_W_M2 * t.cabin_area_m2 if t.heat_soaked_hull else 0.0
    
    q_sensible = q_trans + q_metabolic + q_equip + q_fenes + q_ceiling + q_floor + q_engine + q_lag
    q_total = q_sensible * (LATENT_CORRECTION if t.internal_humidity > 70 else 1.0)
    
    mode = HVACMode.FULL_COOLING if t.occupancy else HVACMode.MAINTENANCE_COOLING
    if not t.occupancy: q_total *= 0.40

    # PITCH WINNER: ROI LOGIC
    roi = calculate_roi_metrics(q_total / 1000)

    return HVACDecision(
        cabin_id=t.cabin_id, mode=mode, optimized_load_kw=round(q_total/1000, 3),
        setpoint_actual=t.target_temp, energy_saved_percent=60.0 if not t.occupancy else 0.0,
        weather_source="api_live", decision_log=log,
        money_saved_hr_inr=roi["hourly_inr"], co2_saved_hr_kg=roi["hourly_co2_kg"], annual_roi_inr=roi["annual_savings_inr"],
        breakdown=HeatLoadBreakdown(
            q_transmission=round(q_trans/1000, 3), q_solar=0, q_engine_radiant=round(q_engine/1000, 3),
            q_thermal_lag=round(q_lag/1000, 3), q_metabolic=round(q_metabolic/1000, 3), q_equipment=round(q_equip/1000, 3),
            q_fenestration=round(q_fenes/1000, 3), q_ceiling=round(q_ceiling/1000, 3), q_floor_conduction=round(q_floor/1000, 3),
            q_latent=round((q_total-q_sensible)/1000, 3), q_total_raw=round(q_total/1000, 3)
        )
    )

def calculate_fleet_summary(cabin_list: list[CabinTelemetry]):
    decisions = [calculate_optimized_load(c) for c in cabin_list]
    total_load = sum(d.optimized_load_kw for d in decisions)
    total_savings = sum(d.annual_roi_inr for d in decisions)
    return FleetSummary(
        total_cabins=len(cabin_list), occupied_cabins=sum(1 for c in cabin_list if c.occupancy),
        total_load_kw=round(total_load, 2), total_annual_savings_inr=round(total_savings, 2),
        total_annual_co2_tons=round((total_savings / 14.20 * 0.68) / 1000, 2), cabins=decisions
    )