"""
MAR-HVAC AI — Asset Defence Module
backend/asset_defence.py

WEEK 4 — YOU build this file.

What this file does:
  1. Calculates dew point — if internal temp drops below dew point,
     condensation forms on steel hull → corrosion starts
  2. Detects mold risk — if humidity stays above threshold for too long
  3. Enforces hospital-grade thresholds when market_segment = "hospital"
  4. Returns an AssetDefenceResult that main.py injects into every /optimize call

WHY THIS MATTERS FOR THE PITCH:
  - Ship hull corrosion costs owners $2M+ in repairs
  - Black mold in passenger cabins = lawsuits
  - Ship hospitals with infected mold = life threatening
  - We are the ONLY HVAC system that monitors and prevents this
  - Corrosion Prevention is the biggest differentiator vs competitors

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

# How close to dew point before we trigger Corrosion Prevention mode
# (1.0 degree C safety margin — act before condensation actually starts)
DEW_POINT_SAFETY_MARGIN_C = 1.0

# Mold grows when RH stays above this for too long
MOLD_RH_THRESHOLD = {
    "cargo":    70.0,
    "cruise":   65.0,
    "navy":     60.0,
    "hospital": 55.0,   # strictest — infection control is life-or-death
    "yacht":    60.0,
}

# How many minutes of high humidity before mold alert fires
MOLD_DURATION_MINUTES = 15   # In production this would be 4 hours
                              # Shortened to 15min for demo / testing

# Hospital mode — strict temperature and humidity bands
# Based on WHO guidelines for healthcare facility air quality
HOSPITAL_TEMP_MIN = 20.0   # degrees C
HOSPITAL_TEMP_MAX = 22.0
HOSPITAL_RH_MIN   = 45.0   # %RH
HOSPITAL_RH_MAX   = 55.0

# Medicine refrigeration room — separate stricter zone
MEDICINE_ROOM_TEMP_MAX = 8.0    # degrees C (vaccine cold chain)
MEDICINE_ROOM_RH_MAX   = 50.0


# ─────────────────────────────────────────────────────────────
# HIGH-HUMIDITY TRACKER
# Tracks how long each cabin has had dangerous humidity
# Module-level dict — persists across requests like weather cache
# ─────────────────────────────────────────────────────────────

# Format: { "cabin_id": timestamp_when_high_humidity_started }
_high_humidity_start: dict[str, float] = {}


def _record_high_humidity(cabin_id: str, rh: float, threshold: float) -> float:
    """
    Track how long this cabin has been above the humidity threshold.
    Returns duration in minutes.
    """
    now = time.time()

    if rh > threshold:
        # First time we see high humidity for this cabin — record the start time
        if cabin_id not in _high_humidity_start:
            _high_humidity_start[cabin_id] = now
            logger.info(f"[ASSET] {cabin_id}: High humidity started ({rh:.0f}%RH > {threshold:.0f}%)")
        duration_minutes = (now - _high_humidity_start[cabin_id]) / 60.0
        return duration_minutes
    else:
        # Humidity is fine — clear the tracker for this cabin
        if cabin_id in _high_humidity_start:
            logger.info(f"[ASSET] {cabin_id}: Humidity back to normal ({rh:.0f}%RH). Clearing timer.")
            del _high_humidity_start[cabin_id]
        return 0.0


def get_high_humidity_duration_minutes(cabin_id: str) -> float:
    """How long has this cabin been above its humidity threshold? Returns 0 if normal."""
    if cabin_id not in _high_humidity_start:
        return 0.0
    return (time.time() - _high_humidity_start[cabin_id]) / 60.0


# ─────────────────────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────────────────────

@dataclass
class AssetDefenceResult:
    """
    Result from running asset defence checks on a cabin.
    Returned to hvac_engine.py and main.py to influence the HVACDecision.
    """
    # Dew point check
    dew_point_c          : float = 0.0
    corrosion_risk       : bool  = False   # True = internal temp near dew point
    corrosion_severity   : str   = "none"  # "none" | "warning" | "critical"

    # Mold check
    mold_risk            : bool  = False   # True = humidity too high too long
    high_humidity_minutes: float = 0.0
    mold_threshold_rh    : float = 70.0

    # Hospital mode
    hospital_mode_active  : bool  = False
    hospital_temp_ok      : bool  = True
    hospital_rh_ok        : bool  = True
    hospital_violations   : list[str] = field(default_factory=list)

    # Recommended HVAC action
    recommended_fan_speed : float = 0.0   # 0.0 to 1.0 — fraction of max fan speed
    recommended_action    : str   = "none"

    # Explanation lines for the AI Decision Log
    log_lines: list[str] = field(default_factory=list)
    warnings:  list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# DEW POINT CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate_dew_point(temp_c: float, rh_percent: float) -> float:
    """
    Magnus formula approximation for dew point.
    Td = T - ((100 - RH) / 5)

    Example:
      temp = 24C, RH = 80% -> Td = 24 - (20/5) = 24 - 4 = 20C
      If internal temp drops to 20C or below -> condensation starts

    This is fast and accurate enough for HVAC control purposes.
    (Error < 1C for RH > 50%, which is always the case on ships)
    """
    return temp_c - ((100.0 - rh_percent) / 5.0)


# ─────────────────────────────────────────────────────────────
# MAIN ASSET DEFENCE CHECK
# ─────────────────────────────────────────────────────────────

def run_asset_defence_checks(
    cabin_id       : str,
    internal_temp  : float,
    internal_rh    : float,
    market_segment : str  = "cargo",
    is_medicine_room: bool = False,
) -> AssetDefenceResult:
    """
    Run all asset defence checks for one cabin.

    Called by hvac_engine.calculate_optimized_load() before the AI decision.

    Args:
      cabin_id        : e.g. "CABIN-A3" — used for humidity duration tracking
      internal_temp   : DHT22 reading in degrees C
      internal_rh     : DHT22 relative humidity in %
      market_segment  : "cargo" | "cruise" | "navy" | "hospital" | "yacht"
      is_medicine_room: True only for ship hospital medicine/vaccine storage room

    Returns:
      AssetDefenceResult with all checks filled in
    """
    result = AssetDefenceResult()
    log    = result.log_lines
    warns  = result.warnings

    log.append("--- ASSET DEFENCE CHECKS ---")

    # ── CHECK 1: Dew Point / Corrosion Risk ──────────────────
    dew_pt = calculate_dew_point(internal_temp, internal_rh)
    result.dew_point_c = round(dew_pt, 2)

    temp_above_dew = internal_temp - dew_pt
    log.append(f"  Dew Point  : {dew_pt:.1f}C")
    log.append(f"  Temp margin: {temp_above_dew:.1f}C above dew point")

    if temp_above_dew <= DEW_POINT_SAFETY_MARGIN_C:
        # CRITICAL — condensation is happening or about to happen RIGHT NOW
        result.corrosion_risk     = True
        result.corrosion_severity = "critical"
        result.recommended_fan_speed = 0.30   # 30% fan speed circulates air, prevents condensation
        result.recommended_action    = "CORROSION_PREVENTION"
        log.append(f"  ! CRITICAL: Temp {internal_temp:.1f}C is {temp_above_dew:.1f}C above dew point {dew_pt:.1f}C")
        log.append(f"  ! CORROSION PREVENTION: Running fans at 30% to circulate air.")
        warns.append(
            f"CORROSION RISK: Internal temp {internal_temp:.1f}C is only "
            f"{temp_above_dew:.1f}C above dew point {dew_pt:.1f}C. "
            f"Condensation on hull steel is imminent. Fan circulation activated."
        )
    elif temp_above_dew <= 3.0:
        # WARNING — getting close, watch carefully
        result.corrosion_risk     = True
        result.corrosion_severity = "warning"
        result.recommended_fan_speed = 0.20
        result.recommended_action    = "CORROSION_PREVENTION"
        log.append(f"  WARNING: Margin only {temp_above_dew:.1f}C. Approaching condensation risk.")
        log.append(f"  Preemptive fans at 20% to maintain air circulation.")
        warns.append(
            f"CORROSION WARNING: Temp margin {temp_above_dew:.1f}C is low. "
            f"Monitor closely. Fan circulation recommended."
        )
    else:
        log.append(f"  OK: {temp_above_dew:.1f}C safety margin — no corrosion risk.")

    # ── CHECK 2: Mold Detection ───────────────────────────────
    mold_threshold = MOLD_RH_THRESHOLD.get(market_segment, 70.0)
    result.mold_threshold_rh = mold_threshold

    duration_minutes = _record_high_humidity(cabin_id, internal_rh, mold_threshold)
    result.high_humidity_minutes = round(duration_minutes, 1)

    log.append(f"  Humidity   : {internal_rh:.0f}%RH (threshold: {mold_threshold:.0f}%)")

    if internal_rh > mold_threshold and duration_minutes >= MOLD_DURATION_MINUTES:
        result.mold_risk = True
        if result.recommended_action == "none":
            result.recommended_action    = "MOLD_ALERT"
            result.recommended_fan_speed = 0.35
        log.append(f"  ! MOLD ALERT: RH {internal_rh:.0f}% for {duration_minutes:.0f} min (>{MOLD_DURATION_MINUTES} min threshold).")
        log.append(f"  ! Dehumidification cycle and increased ventilation required.")
        warns.append(
            f"MOLD ALERT: Humidity {internal_rh:.0f}%RH has exceeded {mold_threshold:.0f}% "
            f"for {duration_minutes:.0f} minutes. Mold growth risk. Dehumidify immediately."
        )
    elif internal_rh > mold_threshold:
        log.append(f"  WATCH: RH {internal_rh:.0f}% is above threshold. Timer: {duration_minutes:.0f} min/{MOLD_DURATION_MINUTES} min.")
    else:
        log.append(f"  OK: Humidity within safe range.")

    # ── CHECK 3: Hospital Mode ────────────────────────────────
    if market_segment == "hospital":
        result.hospital_mode_active = True
        log.append("  HOSPITAL MODE: Applying WHO healthcare air quality standards.")

        if is_medicine_room:
            # Extra strict for vaccine / medicine cold storage
            if internal_temp > MEDICINE_ROOM_TEMP_MAX:
                result.hospital_temp_ok = False
                v = f"MEDICINE ROOM: Temp {internal_temp:.1f}C exceeds {MEDICINE_ROOM_TEMP_MAX}C max! Cold chain at risk."
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")
            if internal_rh > MEDICINE_ROOM_RH_MAX:
                result.hospital_rh_ok = False
                v = f"MEDICINE ROOM: RH {internal_rh:.0f}% exceeds {MEDICINE_ROOM_RH_MAX:.0f}% max! Drug stability at risk."
                result.hospital_violations.append(v)
                warns.append(v)
                log.append(f"  ! {v}")
        else:
            # Standard hospital patient/treatment room
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

    log.append("")   # blank line before AI Decision section

    return result


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("\n=== MAR-HVAC asset_defence.py Test ===\n")

    # Test 1: Normal cabin — no risk
    print("Test 1: Normal cargo cabin (no risk expected)")
    r = run_asset_defence_checks("CABIN-A1", internal_temp=26.0, internal_rh=60.0, market_segment="cargo")
    print(f"  Corrosion risk: {r.corrosion_risk} | Mold risk: {r.mold_risk} | Action: {r.recommended_action}")

    # Test 2: Corrosion risk — temp near dew point
    print("\nTest 2: Cold cabin near dew point (corrosion expected)")
    # temp=20, rh=85 -> dew_point = 20 - (15/5) = 17C -> margin = 3C -> warning
    r = run_asset_defence_checks("CABIN-B2", internal_temp=18.5, internal_rh=88.0, market_segment="cargo")
    print(f"  Dew point: {r.dew_point_c}C | Corrosion: {r.corrosion_risk} ({r.corrosion_severity}) | Action: {r.recommended_action}")
    for line in r.log_lines: print(f"  {line}")

    # Test 3: Hospital mode
    print("\nTest 3: Hospital mode (strict thresholds)")
    r = run_asset_defence_checks("HOSPITAL-01", internal_temp=24.0, internal_rh=68.0, market_segment="hospital")
    print(f"  Hospital mode: {r.hospital_mode_active} | Temp OK: {r.hospital_temp_ok} | RH OK: {r.hospital_rh_ok}")
    print(f"  Violations: {r.hospital_violations}")

    # Test 4: Simulate mold buildup — call multiple times to trigger timer
    print("\nTest 4: High humidity mold detection")
    cabin = "CABIN-C3"
    for i in range(3):
        r = run_asset_defence_checks(cabin, internal_temp=27.0, internal_rh=75.0, market_segment="cargo")
        print(f"  Call {i+1}: RH=75%, Duration={r.high_humidity_minutes:.1f}min, MoldRisk={r.mold_risk}")
        time.sleep(0.1)

    print("\n=== Test complete ===\n")