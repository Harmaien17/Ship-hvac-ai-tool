import logging
from backend.schemas import WasteHeatInput, WasteHeatResult

logger = logging.getLogger("mar_hvac.waste_heat")

CP_EXHAUST_KJ_PER_KG_K = 1.09   
CO2_KG_PER_KWH_HFO = 0.28

def calculate_waste_heat_recovery(inp: WasteHeatInput) -> WasteHeatResult:
    log: list[str] = ["=== WASTE HEAT RECOVERY ANALYSIS ==="]
    
    delta_t_exhaust = inp.exhaust_temp_c - inp.ambient_temp_c
    q_gross_kw = inp.exhaust_flow_kg_s * CP_EXHAUST_KJ_PER_KG_K * delta_t_exhaust
    q_recoverable_kw = q_gross_kw * inp.recovery_efficiency
    hvac_offset_kw = q_recoverable_kw
    co2_saved_per_hr = q_recoverable_kw * CO2_KG_PER_KWH_HFO

    log.append(f"  Q_recoverable: {q_recoverable_kw:.1f} kW recovery potential")
    log.append(f"  CO2 saved: {co2_saved_per_hr:.2f} kg/hr")

    return WasteHeatResult(
        gross_heat_kw=round(q_gross_kw, 2),
        recoverable_kw=round(q_recoverable_kw, 2),
        hvac_offset_kw=round(hvac_offset_kw, 2),
        co2_saved_kg_per_hr=round(co2_saved_per_hr, 3),
        log_lines=log,
    )