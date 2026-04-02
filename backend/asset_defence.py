"""
MAR-HVAC AI — Asset Defence Module (V2.1 - Enhanced Logic Integration)
backend/asset_defence.py
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict

logger = logging.getLogger("mar_hvac.asset_defence")

# ─────────────────────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────────────────────
DEW_POINT_SAFETY_MARGIN_C = 1.0

MOLD_RH_THRESHOLD = {
    "cargo":    70.0,
    "cruise":   65.0,
    "navy":     60.0,
    "hospital": 55.0,   
    "yacht":    60.0,
}

MOLD_DURATION_MINUTES = 15
HOSPITAL_TEMP_MIN, HOSPITAL_TEMP_MAX = 20.0, 22.0
HOSPITAL_RH_MIN, HOSPITAL_RH_MAX = 45.0, 55.0
MEDICINE_TEMP_MAX, MEDICINE_RH_MAX = 8.0, 50.0

# ─────────────────────────────────────────────────────────────
# HUMIDITY TIMER
# ─────────────────────────────────────────────────────────────
_high_rh_start: dict[str, float] = {}

def _update_rh_timer(cabin_id: str, rh: float, threshold: float) -> float:
    now = time.time()
    if rh > threshold:
        if cabin_id not in _high_rh_start:
            _high_rh_start[cabin_id] = now
        return (now - _high_rh_start[cabin_id]) / 60.0
    else:
        if cabin_id in _high_rh_start:
            del _high_rh_start[cabin_id]
        return 0.0

# ─────────────────────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────────────────────
@dataclass
class AssetDefenceResult:
    dew_point_c          : float = 0.0
    corrosion_risk        : bool  = False
    corrosion_severity    : str   = "none"
    mold_risk             : bool  = False
    high_rh_minutes       : float = 0.0
    mold_threshold_rh     : float = 70.0
    hospital_mode         : bool  = False
    hospital_temp_ok      : bool  = True
    hospital_rh_ok        : bool  = True
    hospital_violations   : list[str] = field(default_factory=list)
    heating_required      : bool  = False
    recommended_action    : str   = "none"
    recommended_fan_speed : float = 0.0
    log_lines             : list[str] = field(default_factory=list)
    warnings              : list[str] = field(default_factory=list)

    # Parser Variables
    latent_heat_impact    : float = 0.0   
    hull_thermal_stress   : str   = "low" 
    raw_load_total        : float = 0.0

# ─────────────────────────────────────────────────────────────
# CORE UTILITIES
# ─────────────────────────────────────────────────────────────
def calculate_dew_point(temp_c: float, rh_percent: float) -> float:
    return temp_c - ((100.0 - rh_percent) / 5.0)

def integrate_parser_data(sensor_rh: float, parser_vars: Dict[str, float]) -> Dict[str, any]:
    """Combines live sensors with the 11 variables from the parser."""
    latent_factor = parser_vars.get("latent_heat", 0.0)
    thermal_lag = parser_vars.get("thermal_lag", 0.0)
    
    # Preemptive Logic: If latent heat is high, mold risk is imminent
    adjusted_mold_risk = (sensor_rh > 60.0 and latent_factor > 500.0)
    
    return {
        "adjusted_risk": adjusted_mold_risk,
        "thermal_stress": "high" if thermal_lag > 1000.0 else "low",
        "latent_impact": latent_factor
    }

# ─────────────────────────────────────────────────────────────
# MAIN CHECK FUNCTION
# ─────────────────────────────────────────────────────────────
def run_asset_defence_checks(
    cabin_id        : str,
    internal_temp   : float,
    internal_rh     : float,
    external_temp   : Optional[float] = None,
    target_temp     : float = 22.0,
    market_segment  : str   = "cargo",
    is_medicine_room: bool  = False,
    parser_data     : Optional[Dict[str, float]] = None,
) -> AssetDefenceResult:
    
    result = AssetDefenceResult()
    log, warns = result.log_lines, result.warnings
    log.append("--- ASSET DEFENCE CHECKS ---")

    # 1. Dew Point / Corrosion (Base Logic)
    dew_pt = calculate_dew_point(internal_temp, internal_rh)
    result.dew_point_c = round(dew_pt, 2)
    margin = internal_temp - dew_pt
    if margin <= DEW_POINT_SAFETY_MARGIN_C:
        result.corrosion_risk, result.corrosion_severity = True, "critical"
    
    # 2. Mold Detection (Base Logic)
    mold_thresh = MOLD_RH_THRESHOLD.get(market_segment, 70.0)
    duration = _update_rh_timer(cabin_id, internal_rh, mold_thresh)
    result.high_rh_minutes, result.mold_threshold_rh = round(duration, 1), mold_thresh
    if internal_rh > mold_thresh and duration >= MOLD_DURATION_MINUTES:
        result.mold_risk = True

    # 3. Integrated Parser Logic (Variable 4 & 5 Integration)
    if parser_data:
        impact = integrate_parser_data(internal_rh, parser_data)
        result.latent_heat_impact = impact["latent_impact"]
        result.hull_thermal_stress = impact["thermal_stress"]
        result.raw_load_total = parser_data.get("total_raw_load", 0.0)

        # FIX: Elevated Corrosion Risk based on Variable 4 (Thermal Lag)
        if impact["thermal_stress"] == "high":
            result.corrosion_risk = True
            result.corrosion_severity = "warning"
            warns.append("THERMAL STRESS ALERT: Hull heat-soak detected in blueprints. Risk of rapid corrosion.")

        # FIX: Preemptive Mold Alert based on Variable 5 (Latent Heat)
        if impact["adjusted_risk"] and not result.mold_risk:
            result.mold_risk = True
            result.recommended_action = "PREEMPTIVE_DEHUMIDIFICATION"
            warns.append("PREEMPTIVE ALERT: High Latent Heat load detected from blueprints.")
        elif result.mold_risk:
            result.recommended_action = "MOLD_ALERT"

    # 4. Final Action Mapping
    if result.corrosion_risk and result.corrosion_severity == "critical":
        result.recommended_action = "CORROSION_PREVENTION"
        result.recommended_fan_speed = 0.30

    return result