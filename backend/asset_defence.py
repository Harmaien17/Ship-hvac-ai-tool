"""
MAR-HVAC AI — Asset Defence Module
backend/asset_defence.py

WEEK 4 — complete

What this does:
  1. Dew-point check  -> CORROSION_PREVENTION mode
  2. Mold timer       -> MOLD_ALERT after sustained high humidity
  3. Hospital mode    -> strict WHO temperature + RH bands
  4. Heating mode     -> flag when ext_temp < target (arctic routes)

WHY THIS IS THE BIGGEST PITCH DIFFERENTIATOR:
  - Ship hull corrosion = $2M+ repair bills
  - Black mold in passenger cabins = lawsuits + regulatory fines
  - Ship hospital mold = infection risk, potentially life-threatening
  - No existing marine HVAC product monitors this in real-time

YOU are the only one who edits this file.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("mar_hvac.asset_defence")


# ─────────────────────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────────────────────

# Degrees C safety margin above dew point before triggering prevention
DEW_POINT_SAFETY_MARGIN_C = 1.0

# Per-segment mold RH thresholds (%RH)
MOLD_RH_THRESHOLD = {
    "cargo":    70.0,
    "cruise":   65.0,
    "navy":     60.0,
    "hospital": 55.0,   # strictest — WHO infection control
    "yacht":    60.0,
}

# How long cabin must be above mold RH before alert fires (minutes)
# Production: 4 hours (240 min) | Demo/test: 15 min
MOLD_DURATION_MINUTES = 15

# Hospital-grade thresholds (WHO healthcare air quality guidelines)
HOSPITAL_TEMP_MIN  = 20.0
HOSPITAL_TEMP_MAX  = 22.0
HOSPITAL_RH_MIN    = 45.0
HOSPITAL_RH_MAX    = 55.0
MEDICINE_TEMP_MAX  = 8.0    # vaccine cold chain
MEDICINE_RH_MAX    = 50.0


# ─────────────────────────────────────────────────────────────
# HUMIDITY TIMER — module-level, persists across requests
# ─────────────────────────────────────────────────────────────
# Format: { "CABIN-ID": unix_timestamp_when_high_humidity_started }

_high_rh_start: dict[str, float] = {}


def _update_rh_timer(cabin_id: str, rh: float, threshold: float) -> float:
    """
    Track how long a cabin has been above its mold RH threshold.
    Returns duration in minutes. Resets timer when RH drops below threshold.
    """
    now = time.time()
    if rh > threshold:
        if cabin_id not in _high_rh_start:
            _high_rh_start[cabin_id] = now
        return (now - _high_rh_start[cabin_id]) / 60.0
    else:
        if cabin_id in _high_rh_start:
            del _high_rh_start[cabin_id]
        return 0.0


def get_rh_duration_minutes(cabin_id: str) -> float:
    """How long has this cabin been above its mold threshold? 0 if normal."""
    if cabin_id not in _high_rh_start:
        return 0.0
    return (time.time() - _high_rh_start[cabin_id]) / 60.0


# ─────────────────────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────────────────────

@dataclass
class AssetDefenceResult:
    """All asset defence check results for one cabin."""

    # Dew point
    dew_point_c          : float = 0.0
    corrosion_risk        : bool  = False
    corrosion_severity    : str   = "none"   # none | warning | critical

    # Mold
    mold_risk             : bool  = False
    high_rh_minutes       : float = 0.0
    mold_threshold_rh     : float = 70.0

    # Hospital
    hospital_mode         : bool  = False
    hospital_temp_ok      : bool  = True
    hospital_rh_ok        : bool  = True
    hospital_violations   : list[str] = field(default_factory=list)

    # Heating flag (for dashboard colour switch)
    heating_required      : bool  = False

    # Recommended response
    recommended_action    : str   = "none"
    recommended_fan_speed : float = 0.0   # 0.0 to 1.0

    # Log
    log_lines : list[str] = field(default_factory=list)
    warnings  : list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# DEW POINT
# ─────────────────────────────────────────────────────────────

def calculate_dew_point(temp_c: float, rh_percent: float) -> float:
    """
    Magnus formula: Td = T - ((100 - RH) / 5)
    Accurate within 1C for RH > 50%, which is always true on ships.
    """
    return temp_c - ((100.0 - rh_percent) / 5.0)


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
) -> AssetDefenceResult:
    """
    Run all four asset defence checks for one cabin.

    Args:
      cabin_id         : e.g. "CABIN-A3" (used for mold timer)
      internal_temp    : DHT22 temperature in degrees C
      internal_rh      : DHT22 humidity in %
      external_temp    : from OpenWeather (used for heating check)
      target_temp      : HVAC setpoint in degrees C
      market_segment   : cargo | cruise | navy | hospital | yacht
      is_medicine_room : True only for ship hospital cold-chain room

    Returns:
      AssetDefenceResult with all checks filled in
    """
    result = AssetDefenceResult()
    log    = result.log_lines
    warns  = result.warnings

    log.append("--- ASSET DEFENCE CHECKS ---")

    # ── CHECK 1: Dew Point / Corrosion ───────────────────────
    dew_pt = calculate_dew_point(internal_temp, internal_rh)
    result.dew_point_c = round(dew_pt, 2)
    margin = internal_temp - dew_pt

    log.append(f"  Dew point  : {dew_pt:.1f}C (margin: {margin:.1f}C)")

    if margin <= DEW_POINT_SAFETY_MARGIN_C:
        result.corrosion_risk     = True
        result.corrosion_severity = "critical"
        result.recommended_action = "CORROSION_PREVENTION"
        result.recommended_fan_speed = 0.30
        log.append(f"  ! CRITICAL: {margin:.1f}C margin — condensation on hull steel imminent.")
        log.append(f"  ! Activating fans at 30% to circulate air.")
        warns.append(
            f"CORROSION RISK: Internal {internal_temp:.1f}C is only {margin:.1f}C above "
            f"dew point {dew_pt:.1f}C. Hull condensation imminent."
        )
    elif margin <= 3.0:
        result.corrosion_risk     = True
        result.corrosion_severity = "warning"
        result.recommended_action = "CORROSION_PREVENTION"
        result.recommended_fan_speed = 0.20
        log.append(f"  WARNING: {margin:.1f}C margin is approaching condensation risk.")
        warns.append(
            f"CORROSION WARNING: Temp margin {margin:.1f}C is low. "
            "Fan circulation recommended."
        )
    else:
        log.append(f"  OK: {margin:.1f}C safety margin — no corrosion risk.")

    # ── CHECK 2: Mold Detection ───────────────────────────────
    mold_thresh = MOLD_RH_THRESHOLD.get(market_segment, 70.0)
    result.mold_threshold_rh = mold_thresh
    duration = _update_rh_timer(cabin_id, internal_rh, mold_thresh)
    result.high_rh_minutes = round(duration, 1)

    log.append(f"  Humidity   : {internal_rh:.0f}%RH (threshold: {mold_thresh:.0f}%)")

    if internal_rh > mold_thresh and duration >= MOLD_DURATION_MINUTES:
        result.mold_risk = True
        if result.recommended_action == "none":
            result.recommended_action    = "MOLD_ALERT"
            result.recommended_fan_speed = 0.35
        log.append(f"  ! MOLD ALERT: RH {internal_rh:.0f}% for {duration:.0f} min.")
        warns.append(
            f"MOLD ALERT: Humidity {internal_rh:.0f}%RH > {mold_thresh:.0f}% "
            f"for {duration:.0f} minutes. Dehumidify immediately."
        )
    elif internal_rh > mold_thresh:
        log.append(f"  WATCH: RH above threshold. Timer: {duration:.0f}/{MOLD_DURATION_MINUTES} min.")
    else:
        log.append(f"  OK: Humidity within safe range.")

    # ── CHECK 3: Hospital Compliance ──────────────────────────
    if market_segment == "hospital":
        result.hospital_mode = True
        log.append("  HOSPITAL MODE: Applying WHO healthcare air quality standards.")

        if is_medicine_room:
            if internal_temp > MEDICINE_TEMP_MAX:
                result.hospital_temp_ok = False
                v = f"MEDICINE ROOM: Temp {internal_temp:.1f}C > {MEDICINE_TEMP_MAX}C max — cold chain at risk!"
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")
            if internal_rh > MEDICINE_RH_MAX:
                result.hospital_rh_ok = False
                v = f"MEDICINE ROOM: RH {internal_rh:.0f}% > {MEDICINE_RH_MAX:.0f}% max — drug stability at risk!"
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")
        else:
            if not (HOSPITAL_TEMP_MIN <= internal_temp <= HOSPITAL_TEMP_MAX):
                result.hospital_temp_ok = False
                v = f"HOSPITAL: Temp {internal_temp:.1f}C outside {HOSPITAL_TEMP_MIN}-{HOSPITAL_TEMP_MAX}C WHO range."
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")
            if not (HOSPITAL_RH_MIN <= internal_rh <= HOSPITAL_RH_MAX):
                result.hospital_rh_ok = False
                v = f"HOSPITAL: RH {internal_rh:.0f}% outside {HOSPITAL_RH_MIN:.0f}-{HOSPITAL_RH_MAX:.0f}% WHO range."
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")

        if result.hospital_temp_ok and result.hospital_rh_ok:
            log.append("  OK: Hospital environment within WHO guidelines.")

    # ── CHECK 4: Heating Required ─────────────────────────────
    if external_temp is not None and external_temp < target_temp - 2.0:
        result.heating_required = True
        log.append(f"  HEATING: External {external_temp:.1f}C < setpoint {target_temp:.1f}C.")
        log.append(f"  Arctic/cold route detected. Dashboard will switch to blue theme.")

    log.append("")
    return result