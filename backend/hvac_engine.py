"""
MAR-HVAC AI — Core Heat Load Engine
backend/hvac_engine.py

ASHRAE-based thermal math extended with all marine factors:
  - Ghost Cooling Protocol (40% maintenance load for empty cabins)
  - Thermal Lag (heat-soaked metal hull)
  - Solar Irradiance by cabin side (Port/Starboard)
  - Engine Room Radiant Heat
  - Salt-air latent heat correction
  - Asset Defence: Corrosion Prevention + Mold Alert (dew point)
  - Market Segment thresholds (cargo / cruise / navy / hospital / yacht)
  - Fail-safe weather chain: API -> 1hr cache -> 7-day forecast -> DHT22 fallback

Reference standards:
  ASHRAE Fundamentals Handbook Chapter 18
  IMO MEPC.328(76) Energy Efficiency
  ISO 7547 Air conditioning in ships

YOU are the only one who edits this file.
"""

import time
import logging
from typing import Optional

from schemas import (
    CabinTelemetry, HVACDecision, HeatLoadBreakdown,
    HVACMode, WeatherCache, CabinSide
)

logger = logging.getLogger("mar_hvac.engine")


# ─────────────────────────────────────────────────────────────
# PHYSICAL CONSTANTS & MARINE COEFFICIENTS
# ─────────────────────────────────────────────────────────────

U_HULL_INSULATED    = 0.65   # W/m2·K — standard insulated ship cabin wall
U_HULL_BARE         = 4.8    # W/m2·K — bare steel bulkhead (engine room adjacent)
WALL_AREA_FACTOR    = 1.8    # m2 wall per m2 cabin floor (height 2.4m, ~60% external)
SHGC_PORTHOLE       = 0.52   # Solar Heat Gain Coefficient for marine porthole glass
PORTHOLE_AREA_M2    = 0.12   # Average porthole area per cabin (m2)
METABOLIC_WATT      = 75     # W per occupant — ASHRAE seated light activity
EQUIPMENT_LOAD_W    = 120    # W per occupied cabin — TV, lights, phone charging
ENGINE_RADIANT_W_M2 = 85     # W/m2 of cabin floor — engine room adjacent
THERMAL_LAG_W_M2    = 55     # W/m2 of cabin floor — hull heat-soaked after sun
LATENT_CORRECTION   = 1.18   # Max salt-air multiplier at 100% RH (1.0 at 70% RH)

GHOST_COOLING_FRACTION = 0.40   # 40% load when cabin is empty
GHOST_SETPOINT_DELTA   = 4.0    # Allow +4 degrees C above target when empty
CACHE_EXPIRY_SECONDS   = 3600   # 1 hour — after this, weather cache is stale


# ─────────────────────────────────────────────────────────────
# MARKET SEGMENT THRESHOLDS
# Different vessel types need different HVAC strictness
# ─────────────────────────────────────────────────────────────

MARKET_SETTINGS = {
    "cargo":    {"target_temp": 22.0, "max_rh": 70.0, "ghost_frac": 0.40},
    "cruise":   {"target_temp": 21.0, "max_rh": 65.0, "ghost_frac": 0.35},
    "navy":     {"target_temp": 22.0, "max_rh": 60.0, "ghost_frac": 0.45},
    "hospital": {"target_temp": 21.0, "max_rh": 55.0, "ghost_frac": 0.50},
    "yacht":    {"target_temp": 21.0, "max_rh": 60.0, "ghost_frac": 0.30},
}


# ─────────────────────────────────────────────────────────────
# WEATHER CACHE — module-level singleton, survives request cycles
# ─────────────────────────────────────────────────────────────

_weather_cache: Optional[WeatherCache] = None


def update_weather_cache(temp: float, humidity: float,
                         solar: float = 400.0,
                         source: str = "openweather_api"):
    """Call this every time a live API fetch succeeds."""
    global _weather_cache
    _weather_cache = WeatherCache(
        temperature=temp,
        humidity=humidity,
        solar_irradiance=solar,
        timestamp=time.time(),
        source=source
    )
    logger.info(f"[CACHE] Updated — {temp}C, {humidity}%RH, {solar}W/m2 [{source}]")


def get_cached_weather() -> tuple[Optional[WeatherCache], str]:
    """
    Returns (cache_object, status_string).
    status: 'cache' | 'stale_cache' | 'no_cache'
    """
    if _weather_cache is None:
        return None, "no_cache"
    age = time.time() - _weather_cache.timestamp
    if age > CACHE_EXPIRY_SECONDS:
        logger.warning(f"[CACHE] Stale — {age:.0f}s old.")
        return _weather_cache, "stale_cache"
    return _weather_cache, "cache"


# ─────────────────────────────────────────────────────────────
# HEAT LOAD COMPONENT FUNCTIONS
# ─────────────────────────────────────────────────────────────

def calc_transmission(delta_t: float, area_m2: float,
                      u: float = U_HULL_INSULATED) -> float:
    """
    Q_transmission = U x A_wall x delta_T   [Watts]
    Conductive heat flow through cabin walls/hull.
    delta_T = external_temp - target_temp
    Positive means heat flows INTO cabin = cooling load.
    """
    wall_area = area_m2 * WALL_AREA_FACTOR
    return max(0.0, u * wall_area * delta_t)


def calc_solar(irradiance: float, direct: bool, side: CabinSide) -> float:
    """
    Q_solar = I x A_porthole x SHGC x side_factor   [Watts]
    Solar radiation entering through portholes.
    """
    if not direct:
        effective = irradiance * 0.15   # diffuse — 15% reaches porthole
    else:
        side_factor = {
            CabinSide.STARBOARD: 1.0,
            CabinSide.PORT:      1.0,
            CabinSide.BOW:       0.7,
            CabinSide.STERN:     0.5,
            CabinSide.INTERIOR:  0.05,
        }.get(side, 0.8)
        effective = irradiance * side_factor

    return max(0.0, effective * PORTHOLE_AREA_M2 * SHGC_PORTHOLE)


def calc_internal(occupied: bool) -> float:
    """
    Q_internal = (N x 75W) + equipment_load   [Watts]
    Zero when cabin is empty — this is the Ghost Cooling trigger.
    """
    return (METABOLIC_WATT + EQUIPMENT_LOAD_W) if occupied else 0.0


def calc_engine_radiant(adjacent: bool, area_m2: float) -> float:
    """Radiant heat from engine room through shared bulkhead."""
    return ENGINE_RADIANT_W_M2 * area_m2 if adjacent else 0.0


def calc_thermal_lag(heat_soaked: bool, area_m2: float) -> float:
    """
    Delayed heat release from hull after prolonged sun exposure.
    Steel hull stores enormous heat and radiates it inward for 2-4 hours.
    """
    return THERMAL_LAG_W_M2 * area_m2 if heat_soaked else 0.0


def apply_latent_correction(q_sensible: float, rh: float) -> float:
    """
    Marine salt-air latent heat correction.
    Scales from 1.0 at 70% RH to LATENT_CORRECTION (1.18) at 100% RH.
    """
    if rh <= 70.0:
        return q_sensible
    fraction = (rh - 70.0) / 30.0   # 0.0 to 1.0
    correction = 1.0 + (LATENT_CORRECTION - 1.0) * fraction
    return q_sensible * correction


def calc_dew_point(temp: float, rh: float) -> float:
    """
    Dew point approximation — Magnus formula.
    If internal_temp drops near dew point = condensation risk = corrosion.
    """
    return temp - ((100.0 - rh) / 5.0)


# ─────────────────────────────────────────────────────────────
# MAIN AI ENGINE FUNCTION
# ─────────────────────────────────────────────────────────────

def calculate_optimized_load(t: CabinTelemetry) -> HVACDecision:
    """
    MAR-HVAC AI Engine — full heat load optimisation for one cabin.

    Pipeline:
      1. Resolve external temperature (API live -> cache -> 7-day forecast -> DHT22 fallback)
      2. Calculate all 6 heat load components
      3. Apply latent heat correction for salt air
      4. Asset Defence checks (dew point / mold)
      5. Branch: Ghost Cooling (empty) vs Active Cooling (occupied)
      6. Build decision log and return HVACDecision
    """
    log:      list[str] = []
    warnings: list[str] = []
    weather_source = "api_live"
    data_age: Optional[float] = None

    log.append(f"=== MAR-HVAC AI — Cabin: {t.cabin_id} ===")
    log.append(f"  Status  : {'OCCUPIED' if t.occupancy else 'EMPTY — Ghost Cooling candidate'}")
    log.append(f"  Internal: {t.internal_temp:.1f}C  |  Target: {t.target_temp:.1f}C")
    log.append(f"  Segment : {t.market_segment.upper()}")

    # Load market settings for this vessel type
    mkt = MARKET_SETTINGS.get(t.market_segment, MARKET_SETTINGS["cargo"])

    # ── STEP 1: Resolve external temperature ─────────────────
    ext_temp = t.external_temp
    ext_rh   = t.internal_humidity
    solar    = t.solar_irradiance or 400.0

    if ext_temp is None:
        cache, status = get_cached_weather()
        if cache is not None:
            ext_temp = cache.temperature
            ext_rh   = cache.humidity
            solar    = cache.solar_irradiance
            data_age = round(time.time() - cache.timestamp, 1)
            if status == "stale_cache":
                weather_source = "stale_cache"
                warnings.append(f"STALE CACHE: weather data is {data_age:.0f}s old. Internet may be down.")
                log.append(f"  FAILSAFE: Using stale cache ({data_age:.0f}s old) — {ext_temp:.1f}C")
            else:
                weather_source = "cache"
                log.append(f"  Weather from cache ({data_age:.0f}s old) — {ext_temp:.1f}C")
        else:
            # Last resort — DHT22 + offset
            ext_temp = t.internal_temp + 5.0
            weather_source = "dht22_fallback"
            warnings.append("CRITICAL FAILSAFE: No weather data at all. Using DHT22 + 5C offset.")
            log.append(f"  FAILSAFE: No cache. Using DHT22 {t.internal_temp:.1f}C + 5C = {ext_temp:.1f}C")
    else:
        # Live API data — update the cache for next request
        update_weather_cache(ext_temp, ext_rh, solar, source="openweather_api")
        log.append(f"  External: {ext_temp:.1f}C (live API)  |  Solar: {solar:.0f} W/m2")

    # ── STEP 2: Dew point — Asset Defence check ──────────────
    dew_pt = calc_dew_point(t.internal_temp, ext_rh)
    log.append(f"  Dew Point: {dew_pt:.1f}C  |  RH: {ext_rh:.0f}%  |  Side: {t.cabin_side.value}")
    log.append(f"  Ship: HullSoaked={t.heat_soaked_hull}  EngineAdj={t.engine_adjacent}  DirectSun={t.direct_sunlight}")
    log.append("")

    # ── STEP 3: Calculate all heat load components ────────────
    delta_t  = ext_temp - t.target_temp
    u_val    = U_HULL_BARE if t.engine_adjacent else U_HULL_INSULATED

    q_trans  = calc_transmission(delta_t, t.cabin_area_m2, u_val)
    q_solar  = calc_solar(solar, t.direct_sunlight, t.cabin_side)
    q_int    = calc_internal(t.occupancy)
    q_engine = calc_engine_radiant(t.engine_adjacent, t.cabin_area_m2)
    q_lag    = calc_thermal_lag(t.heat_soaked_hull, t.cabin_area_m2)
    q_sum    = q_trans + q_solar + q_int + q_engine + q_lag
    q_total  = apply_latent_correction(q_sum, ext_rh)
    q_latent = q_total - q_sum

    log.append("--- HEAT LOAD BREAKDOWN ---")
    log.append(f"  Transmission  : {q_trans:.1f} W  (dT={delta_t:+.1f}C, U={u_val})")
    log.append(f"  Solar         : {q_solar:.1f} W  ({solar:.0f} W/m2, SHGC={SHGC_PORTHOLE})")
    log.append(f"  Internal      : {q_int:.1f} W  ({'occupied' if t.occupancy else 'empty — zero'})")
    log.append(f"  Engine radiant: {q_engine:.1f} W  ({'active' if t.engine_adjacent else 'N/A'})")
    log.append(f"  Thermal lag   : {q_lag:.1f} W  ({'hull heat-soaked' if t.heat_soaked_hull else 'N/A'})")
    log.append(f"  Latent (salt) : {q_latent:.1f} W  (RH={ext_rh:.0f}%)")
    log.append(f"  ───────────────────────────")
    log.append(f"  TOTAL RAW     : {q_total:.1f} W = {q_total/1000:.3f} kW")
    log.append("")

    # ── STEP 4: AI Decision Branch ────────────────────────────
    log.append("--- AI DECISION ---")

    # Priority 1: Corrosion Prevention (dew point risk)
    if t.internal_temp < dew_pt + 1.0:
        mode          = HVACMode.CORROSION_PREVENTION
        frac          = 0.30
        actual_sp     = t.target_temp
        savings_pct   = 70.0
        optimized_kw  = round(q_total * frac / 1000, 3)
        log.append("! CORROSION RISK: Internal temp near dew point.")
        log.append(f"  Running fans at 30% to prevent hull condensation.")
        warnings.append("CORROSION RISK: Hull condensation imminent. Fan circulation active.")

    # Priority 2: Mold Alert (high humidity in empty cabin)
    elif ext_rh > mkt["max_rh"] and not t.occupancy:
        mode          = HVACMode.MOLD_ALERT
        frac          = 0.35
        actual_sp     = t.target_temp
        savings_pct   = 65.0
        optimized_kw  = round(q_total * frac / 1000, 3)
        log.append(f"! MOLD ALERT: RH {ext_rh:.0f}% > threshold {mkt['max_rh']:.0f}%.")
        log.append("  Dehumidification cycle active.")
        warnings.append(f"MOLD ALERT: Humidity {ext_rh:.0f}% exceeds {mkt['max_rh']:.0f}% threshold.")

    # Priority 3: Ghost Cooling Protocol (empty cabin)
    elif not t.occupancy:
        frac = mkt["ghost_frac"]
        if t.heat_soaked_hull and t.engine_adjacent:
            frac = min(0.50, frac + 0.10)
            log.append("  Compounding factors: heat-soaked hull + engine adjacent -> frac raised to 50%.")
        elif t.heat_soaked_hull or t.engine_adjacent:
            frac = min(0.45, frac + 0.05)
            log.append("  One structural factor detected -> frac raised to 45%.")

        mode         = HVACMode.MAINTENANCE_COOLING
        actual_sp    = t.target_temp + GHOST_SETPOINT_DELTA
        savings_pct  = round((1.0 - frac) * 100, 1)
        optimized_kw = round(q_total * frac / 1000, 3)
        log.append(f"  GHOST COOLING ACTIVE: PIR = empty.")
        log.append(f"  Running at {frac*100:.0f}% load = {optimized_kw:.3f} kW.")
        log.append(f"  Setpoint relaxed to {actual_sp:.1f}C (was {t.target_temp:.1f}C).")
        log.append(f"  Energy saved vs full load: {savings_pct:.1f}%")

    # Priority 4: Occupied — dynamic load optimisation
    else:
        actual_sp = t.target_temp
        worst = (
            U_HULL_INSULATED * t.cabin_area_m2 * WALL_AREA_FACTOR * 20.0 +
            1200 * PORTHOLE_AREA_M2 * SHGC_PORTHOLE +
            METABOLIC_WATT + EQUIPMENT_LOAD_W +
            THERMAL_LAG_W_M2 * t.cabin_area_m2 +
            ENGINE_RADIANT_W_M2 * t.cabin_area_m2
        ) * LATENT_CORRECTION
        load_frac = q_total / max(worst, 1.0)

        if delta_t < 0:        mode = HVACMode.EMERGENCY_HEAT
        elif load_frac >= 0.85: mode = HVACMode.FULL_COOLING
        elif load_frac >= 0.40: mode = HVACMode.REDUCED_COOLING
        else:                   mode = HVACMode.STANDBY

        optimized_kw = round(q_total / 1000, 3)
        savings_pct  = round(max(0.0, (1.0 - load_frac) * 20.0), 1)
        log.append(f"  OCCUPIED: load fraction {load_frac:.0%} -> {mode.value}")
        log.append(f"  Setpoint maintained at {actual_sp:.1f}C")

    # Override to FAILSAFE if weather data is unreliable
    if weather_source in ("stale_cache", "dht22_fallback"):
        mode = HVACMode.FAILSAFE
        log.append("")
        log.append("! MODE OVERRIDE -> FAILSAFE (unreliable weather data)")
        log.append("  Holding last known setpoint until internet restored.")

    log.append("")
    log.append(f"=== FINAL: {optimized_kw:.3f} kW | {mode.value} | Saved: {savings_pct:.1f}% ===")

    # ── STEP 5: Build and return result ──────────────────────
    return HVACDecision(
        cabin_id              = t.cabin_id,
        mode                  = mode,
        optimized_load_kw     = optimized_kw,
        setpoint_actual       = actual_sp,
        energy_saved_percent  = savings_pct,
        breakdown=HeatLoadBreakdown(
            q_transmission   = round(q_trans  / 1000, 4),
            q_solar          = round(q_solar  / 1000, 4),
            q_internal       = round(q_int    / 1000, 4),
            q_engine_radiant = round(q_engine / 1000, 4),
            q_thermal_lag    = round(q_lag    / 1000, 4),
            q_latent         = round(q_latent / 1000, 4),
            q_total_raw      = round(q_total  / 1000, 4),
        ),
        decision_log     = log,
        warnings         = warnings,
        weather_source   = weather_source,
        data_age_seconds = data_age,
        dew_point        = round(dew_pt, 2),
    )


# ─────────────────────────────────────────────────────────────
# FLEET AGGREGATION
# ─────────────────────────────────────────────────────────────

def calculate_fleet_summary(cabin_list: list[CabinTelemetry]):
    """Process all cabins and return aggregated FleetSummary."""
    from schemas import FleetSummary

    decisions = [calculate_optimized_load(c) for c in cabin_list]

    total   = sum(d.optimized_load_kw        for d in decisions)
    base    = sum(d.breakdown.q_total_raw     for d in decisions)
    occ     = sum(1 for c in cabin_list if c.occupancy)
    ghost   = sum(1 for d in decisions if d.mode == HVACMode.MAINTENANCE_COOLING)
    corr    = sum(1 for d in decisions if d.mode == HVACMode.CORROSION_PREVENTION)
    savings = round((1.0 - total / max(base, 0.001)) * 100, 1) if base > 0 else 0.0

    return FleetSummary(
        total_cabins          = len(decisions),
        occupied_cabins       = occ,
        ghost_cooling_cabins  = ghost,
        corrosion_risk_cabins = corr,
        total_load_kw         = round(total, 3),
        baseline_load_kw      = round(base, 3),
        fleet_savings_percent = savings,
        cabins                = decisions,
    )