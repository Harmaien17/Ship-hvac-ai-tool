"""
MAR-HVAC AI — Core Heat Load Engine
backend/hvac_engine.py

Updated: Week 4 + 5 + 6

New in this version:
  1. occupant_count  -> Q_metabolic  = N * 75W  (replaces bool * 75W)
  2. window_area_m2  -> Q_fenestration = I * A_window * SHGC  (replaces fixed PORTHOLE_AREA_M2)
  3. equipment_wattage -> Q_equipment (replaces fixed 120W constant)
  4. ceiling_exposed_to_sun -> Q_ceiling (solar-air load on roof area)
  5. heat_source_below     -> Q_floor_conduction (deck-to-deck conduction from generator room)

  + Heating Load: when ext_temp < target_temp -> EMERGENCY_HEAT mode
    Q_heat = U * A_wall * |delta_T|  (same formula, opposite direction)

  + HeatLoadBreakdown now has 11 separate line items:
    q_transmission, q_solar (porthole diffuse), q_fenestration (window direct),
    q_metabolic, q_equipment, q_engine_radiant, q_thermal_lag,
    q_ceiling, q_floor_conduction, q_latent, q_waste_heat_saved

Reference standards:
  ASHRAE Fundamentals Handbook Chapter 18 — Nonresidential Cooling/Heating Load
  IMO MEPC.328(76) — Energy Efficiency Existing Ships Index (EEXI)
  ISO 7547 — Air conditioning and heating on ships

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

# Wall / hull heat transfer
U_HULL_INSULATED    = 0.65   # W/m2·K — mineral-wool insulated ship cabin wall
U_HULL_BARE         = 4.8    # W/m2·K — bare steel bulkhead (engine room shared wall)
U_DECK_SLAB         = 1.2    # W/m2·K — steel deck slab (floor/ceiling between decks)
U_ROOF_EXPOSED      = 2.8    # W/m2·K — upper deck roof directly under sun

WALL_AREA_FACTOR    = 1.8    # m2 wall area per m2 cabin floor
                              # (ceiling height 2.4m, 4 walls, ~60% external exposure)

# Solar
SHGC_PORTHOLE       = 0.52   # Solar Heat Gain Coefficient — tinted marine porthole glass
SHGC_WINDOW         = 0.65   # SHGC for larger marine windows / skylights
PORTHOLE_AREA_M2    = 0.12   # Fallback porthole area if window_area_m2 not specified

# Sol-air temperature delta for sun-exposed deck/roof (ASHRAE sol-air method)
# This is the equivalent extra delta_T added to roof U*A calculation when sun is overhead
SOL_AIR_DELTA_T     = 15.0   # degrees C — peak summer sun on painted steel roof

# Internal heat generation
METABOLIC_W_PER_PERSON = 75  # W per occupant — ASHRAE Table 1, seated light activity
DEFAULT_EQUIPMENT_W    = 120  # W baseline (TV + lights) — used only if equipment_wattage not set

# Heat from adjacent spaces
ENGINE_RADIANT_W_M2    = 85  # W/m2 — from engine room through shared bulkhead
GENERATOR_CONDUCTION_W_M2 = 70  # W/m2 — from generator/boiler room through floor slab
THERMAL_LAG_W_M2       = 55  # W/m2 — delayed hull heat from heat-soaked steel

# Salt-air latent heat correction
LATENT_CORRECTION   = 1.18   # Multiplier at 100% RH (1.0 at <= 70% RH)

# Ghost Cooling Protocol
GHOST_COOLING_FRACTION = 0.40   # 40% of calculated load when cabin is empty
GHOST_SETPOINT_DELTA   = 4.0    # Relax setpoint by +4C when empty to save energy

# Weather cache
CACHE_EXPIRY_SECONDS   = 3600   # 1 hour

# Heating efficiency (COP of marine heat pump / electric resistance)
COP_HEATING = 2.8   # Coefficient of Performance for heating mode


# ─────────────────────────────────────────────────────────────
# MARKET SEGMENT THRESHOLDS
# ─────────────────────────────────────────────────────────────

MARKET_SETTINGS = {
    "cargo":    {"target_temp": 22.0, "max_rh": 70.0, "ghost_frac": 0.40},
    "cruise":   {"target_temp": 21.0, "max_rh": 65.0, "ghost_frac": 0.35},
    "navy":     {"target_temp": 22.0, "max_rh": 60.0, "ghost_frac": 0.45},
    "hospital": {"target_temp": 21.0, "max_rh": 55.0, "ghost_frac": 0.50},
    "yacht":    {"target_temp": 21.0, "max_rh": 60.0, "ghost_frac": 0.30},
}


# ─────────────────────────────────────────────────────────────
# WEATHER CACHE — module-level singleton
# ─────────────────────────────────────────────────────────────

_weather_cache: Optional[WeatherCache] = None


def update_weather_cache(temp: float, humidity: float,
                         solar: float = 400.0,
                         source: str = "openweather_api"):
    global _weather_cache
    _weather_cache = WeatherCache(
        temperature=temp, humidity=humidity,
        solar_irradiance=solar, timestamp=time.time(), source=source
    )
    logger.info(f"[CACHE] {temp}C, {humidity}%RH, {solar}W/m2 [{source}]")


def get_cached_weather() -> tuple[Optional[WeatherCache], str]:
    """Returns (cache, status). status: 'cache' | 'stale_cache' | 'no_cache'"""
    if _weather_cache is None:
        return None, "no_cache"
    age = time.time() - _weather_cache.timestamp
    if age > CACHE_EXPIRY_SECONDS:
        logger.warning(f"[CACHE] Stale — {age:.0f}s old.")
        return _weather_cache, "stale_cache"
    return _weather_cache, "cache"


# ─────────────────────────────────────────────────────────────
# HEAT LOAD COMPONENT FUNCTIONS
# Each function maps to one row in HeatLoadBreakdown
# ─────────────────────────────────────────────────────────────

def calc_wall_transmission(delta_t: float, area_m2: float,
                           u: float = U_HULL_INSULATED) -> float:
    """
    Q_wall = U * A_wall * delta_T   [Watts]

    Steady-state conduction through cabin walls and vertical hull panels.
    delta_T = external_temp - target_temp
    Positive = heat flows INTO cabin (cooling load).
    Negative = heat flows OUT (heating load — handled separately).
    """
    wall_area = area_m2 * WALL_AREA_FACTOR
    return max(0.0, u * wall_area * delta_t)   # cooling component only


def calc_heating_load(delta_t: float, area_m2: float,
                      u: float = U_HULL_INSULATED) -> float:
    """
    Q_heat = U * A_wall * |delta_T|   [Watts]

    Called when ext_temp < target_temp (arctic routes).
    Returns the amount of heat the HVAC must SUPPLY to maintain setpoint.
    delta_T here is negative, so we take the absolute value.
    """
    wall_area = area_m2 * WALL_AREA_FACTOR
    return max(0.0, u * wall_area * abs(delta_t))


def calc_solar_porthole(irradiance: float, direct: bool,
                        side: CabinSide) -> float:
    """
    Q_solar_porthole = I * A_porthole * SHGC_porthole * side_factor   [Watts]

    Diffuse solar gain through fixed portholes.
    Uses the old fixed PORTHOLE_AREA_M2 constant.
    For user-specified window area, see calc_fenestration() below.
    """
    if not direct:
        effective = irradiance * 0.15   # diffuse radiation — 15% reaches porthole
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


def calc_fenestration(irradiance: float, window_area_m2: float,
                      direct: bool, side: CabinSide) -> float:
    """
    NEW — WEEK 4
    Q_fenestration = I * A_window * SHGC_window * side_factor   [Watts]

    Solar gain through user-specified glazed area (portholes + windows).
    Uses window_area_m2 from CabinTelemetry instead of the fixed constant.
    SHGC_WINDOW = 0.65 for larger marine windows.

    Note: if window_area_m2 == 0.12 (default porthole), this gives
    a slightly different result than calc_solar_porthole due to different SHGC.
    """
    if window_area_m2 <= 0.0:
        return 0.0
    if not direct:
        effective = irradiance * 0.15
    else:
        side_factor = {
            CabinSide.STARBOARD: 1.0,
            CabinSide.PORT:      1.0,
            CabinSide.BOW:       0.7,
            CabinSide.STERN:     0.5,
            CabinSide.INTERIOR:  0.05,
        }.get(side, 0.8)
        effective = irradiance * side_factor
    return max(0.0, effective * window_area_m2 * SHGC_WINDOW)


def calc_metabolic(occupant_count: int) -> float:
    """
    NEW — WEEK 4
    Q_metabolic = N_occupants * 75 W   [Watts]

    Replaces the old binary (occupied? 75W : 0) logic.
    Now uses the exact occupant_count from the PIR sensor / capacity data.
    ASHRAE Table 1: 75W sensible heat per person, seated, light activity.
    """
    return max(0.0, float(occupant_count) * METABOLIC_W_PER_PERSON)


def calc_equipment(equipment_wattage: float) -> float:
    """
    NEW — WEEK 4
    Q_equipment = equipment_wattage   [Watts]

    Direct use of the user-supplied equipment load.
    Examples:
      Standard cabin  -> 120W (TV, lights, charger)
      Galley          -> 2000W (electric stoves, refrigerators)
      Server room     -> 5000W (networking racks)
      Hospital room   -> 500W (monitors, IV pumps, lighting)
    """
    return max(0.0, equipment_wattage)


def calc_engine_radiant(adjacent: bool, area_m2: float) -> float:
    """
    Q_engine = ENGINE_RADIANT_W_M2 * A_floor   [Watts]
    Radiant heat through shared vertical bulkhead with engine room.
    """
    return ENGINE_RADIANT_W_M2 * area_m2 if adjacent else 0.0


def calc_thermal_lag(heat_soaked: bool, area_m2: float) -> float:
    """
    Q_lag = THERMAL_LAG_W_M2 * A_floor   [Watts]
    Delayed release from steel hull after prolonged sun exposure.
    """
    return THERMAL_LAG_W_M2 * area_m2 if heat_soaked else 0.0


def calc_ceiling_solar(irradiance: float, exposed: bool,
                       area_m2: float, delta_t: float) -> float:
    """
    NEW — WEEK 4
    Q_ceiling = U_roof * A_floor * (delta_T + SOL_AIR_DELTA_T)   [Watts]

    ASHRAE Sol-Air Method:
    When the ceiling is a sun-exposed deck, solar radiation heats the roof
    steel to well above air temperature. We model this as an equivalent
    extra temperature difference (SOL_AIR_DELTA_T = 15C) added to delta_T.

    Only fires when ceiling_exposed_to_sun = True AND irradiance is meaningful.
    """
    if not exposed or area_m2 <= 0.0:
        return 0.0
    # Only apply if there's meaningful solar radiation (daytime)
    if irradiance < 50.0:
        return 0.0
    effective_delta_t = delta_t + SOL_AIR_DELTA_T
    return max(0.0, U_ROOF_EXPOSED * area_m2 * effective_delta_t)


def calc_floor_conduction(heat_below: bool, area_m2: float,
                          source_temp_c: float = 65.0,
                          cabin_temp_c: float  = 22.0) -> float:
    """
    NEW — WEEK 4
    Q_floor = U_slab * A_floor * (T_source - T_cabin)   [Watts]

    Deck-to-deck conduction from high-heat space below (generator room, boiler).
    T_source defaults to 65C (typical generator room air temperature).
    U_DECK_SLAB = 1.2 W/m2K (uninsulated steel deck).
    """
    if not heat_below or area_m2 <= 0.0:
        return 0.0
    delta_t_floor = source_temp_c - cabin_temp_c
    return max(0.0, U_DECK_SLAB * area_m2 * delta_t_floor)


def apply_latent_correction(q_sensible: float, rh: float) -> float:
    """
    Marine salt-air latent heat correction.
    Multiplier scales from 1.0 at 70% RH to 1.18 at 100% RH.
    """
    if rh <= 70.0:
        return q_sensible
    fraction = (rh - 70.0) / 30.0
    correction = 1.0 + (LATENT_CORRECTION - 1.0) * fraction
    return q_sensible * correction


def calc_dew_point(temp_c: float, rh_percent: float) -> float:
    """
    Dew point: Td = T - ((100 - RH) / 5)   [degrees C]
    Magnus formula approximation. Error < 1C for RH > 50%.
    If internal_temp <= dew_point + 1C -> condensation / corrosion risk.
    """
    return temp_c - ((100.0 - rh_percent) / 5.0)


# ─────────────────────────────────────────────────────────────
# MAIN AI ENGINE FUNCTION
# ─────────────────────────────────────────────────────────────

def calculate_optimized_load(t: CabinTelemetry) -> HVACDecision:
    """
    MAR-HVAC AI Engine — full heat load optimisation for one cabin.

    Pipeline:
      1.  Resolve external weather (API live -> cache -> 7-day forecast -> DHT22)
      2.  Calculate dew point (Asset Defence check)
      3.  Calculate all 11 heat load components
      4.  Apply latent heat correction for salt air
      5.  Calculate heating load if arctic route
      6.  AI Decision Branch:
            - Corrosion Prevention (highest priority)
            - Mold Alert
            - Ghost Cooling (empty cabin)
            - Heating Mode (arctic)
            - Active Cooling (occupied)
      7.  Build HVACDecision and return
    """

    log:      list[str] = []
    warnings: list[str] = []
    weather_source       = "api_live"
    data_age: Optional[float] = None

    log.append(f"=== MAR-HVAC AI — Cabin: {t.cabin_id} | Segment: {t.market_segment.upper()} ===")
    log.append(f"  Occupancy     : {'OCCUPIED (' + str(t.occupant_count) + ' persons)' if t.occupancy else 'EMPTY — Ghost Cooling candidate'}")
    log.append(f"  Internal      : {t.internal_temp:.1f}C | Target: {t.target_temp:.1f}C | RH: {t.internal_humidity:.0f}%")
    log.append(f"  Cabin area    : {t.cabin_area_m2:.1f} m2 | Window area: {t.window_area_m2:.2f} m2")
    log.append(f"  Equipment     : {t.equipment_wattage:.0f} W | Side: {t.cabin_side.value}")

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
                warnings.append(f"STALE CACHE: weather data {data_age:.0f}s old. Internet may be down.")
                log.append(f"  FAILSAFE: Stale cache ({data_age:.0f}s old) — {ext_temp:.1f}C")
            else:
                weather_source = "cache"
                log.append(f"  Weather from cache ({data_age:.0f}s old) — {ext_temp:.1f}C")
        else:
            ext_temp = t.internal_temp + 5.0
            weather_source = "dht22_fallback"
            warnings.append("CRITICAL FAILSAFE: No weather data. Using DHT22 + 5C offset.")
            log.append(f"  FAILSAFE: No cache. DHT22 {t.internal_temp:.1f}C + 5C = {ext_temp:.1f}C")
    else:
        update_weather_cache(ext_temp, ext_rh, solar, source="openweather_api")
        log.append(f"  External      : {ext_temp:.1f}C (live API) | Solar: {solar:.0f} W/m2")

    # ── STEP 2: Dew point ─────────────────────────────────────
    dew_pt = calc_dew_point(t.internal_temp, ext_rh)
    log.append(f"  Dew Point     : {dew_pt:.1f}C (margin: {t.internal_temp - dew_pt:.1f}C above condensation)")
    log.append(f"  Ship flags    : HullSoaked={t.heat_soaked_hull} | EngineAdj={t.engine_adjacent}")
    log.append(f"                  CeilingHot={t.ceiling_exposed_to_sun} | HeatBelow={t.heat_source_below}")
    log.append("")

    # ── STEP 3: Calculate all 11 heat load components ─────────
    delta_t  = ext_temp - t.target_temp   # positive = hotter outside = cooling load
    u_wall   = U_HULL_BARE if t.engine_adjacent else U_HULL_INSULATED

    # Wall transmission (only positive = cooling load here)
    q_trans      = calc_wall_transmission(delta_t, t.cabin_area_m2, u_wall)

    # Heating load (only when ext_temp < target_temp)
    q_heat_load  = calc_heating_load(delta_t, t.cabin_area_m2, u_wall) if delta_t < 0 else 0.0

    # Old porthole solar (diffuse, kept for backward compatibility)
    q_solar      = calc_solar_porthole(solar, t.direct_sunlight, t.cabin_side)

    # NEW: fenestration (user-specified window area)
    q_fenes      = calc_fenestration(solar, t.window_area_m2, t.direct_sunlight, t.cabin_side)

    # NEW: metabolic heat from exact occupant count
    q_metabolic  = calc_metabolic(t.occupant_count)

    # NEW: equipment load from equipment_wattage field
    q_equip      = calc_equipment(t.equipment_wattage)

    # Engine room and hull
    q_engine     = calc_engine_radiant(t.engine_adjacent, t.cabin_area_m2)
    q_lag        = calc_thermal_lag(t.heat_soaked_hull, t.cabin_area_m2)

    # NEW: ceiling solar-air load
    q_ceiling    = calc_ceiling_solar(solar, t.ceiling_exposed_to_sun,
                                      t.cabin_area_m2, delta_t)

    # NEW: floor conduction from heat source below
    q_floor      = calc_floor_conduction(t.heat_source_below, t.cabin_area_m2,
                                         source_temp_c=65.0,
                                         cabin_temp_c=t.internal_temp)

    # Sum of all sensible loads
    q_sensible   = q_trans + q_solar + q_fenes + q_metabolic + q_equip + q_engine + q_lag + q_ceiling + q_floor

    # Salt-air latent correction
    q_total      = apply_latent_correction(q_sensible, ext_rh)
    q_latent     = q_total - q_sensible

    log.append("--- HEAT LOAD BREAKDOWN ---")
    log.append(f"  Wall transmission : {q_trans:.1f} W  (dT={delta_t:+.1f}C, U={u_wall})")
    log.append(f"  Solar porthole    : {q_solar:.1f} W  (diffuse {solar:.0f} W/m2)")
    log.append(f"  Fenestration      : {q_fenes:.1f} W  (window={t.window_area_m2:.2f}m2, SHGC={SHGC_WINDOW})")
    log.append(f"  Metabolic heat    : {q_metabolic:.1f} W  ({t.occupant_count} persons x 75W)")
    log.append(f"  Equipment load    : {q_equip:.1f} W  (from equipment_wattage field)")
    log.append(f"  Engine radiant    : {q_engine:.1f} W  ({'active' if t.engine_adjacent else 'N/A'})")
    log.append(f"  Thermal lag       : {q_lag:.1f} W  ({'hull heat-soaked' if t.heat_soaked_hull else 'N/A'})")
    log.append(f"  Ceiling solar-air : {q_ceiling:.1f} W  ({'sun-exposed roof' if t.ceiling_exposed_to_sun else 'N/A'})")
    log.append(f"  Floor conduction  : {q_floor:.1f} W  ({'heat source below' if t.heat_source_below else 'N/A'})")
    log.append(f"  Latent (salt-air) : {q_latent:.1f} W  (RH={ext_rh:.0f}%)")
    log.append(f"  ──────────────────────────────────────────")
    log.append(f"  TOTAL SENSIBLE    : {q_total:.1f} W = {q_total/1000:.3f} kW")
    if q_heat_load > 0:
        log.append(f"  HEATING LOAD      : {q_heat_load:.1f} W = {q_heat_load/1000:.3f} kW (arctic route)")
    log.append("")

    # ── STEP 4: AI Decision Branch ────────────────────────────
    log.append("--- AI DECISION ---")

    # Priority 1: Corrosion Prevention (dew point breach)
    if t.internal_temp < dew_pt + 1.0:
        mode         = HVACMode.CORROSION_PREVENTION
        frac         = 0.30
        actual_sp    = t.target_temp
        savings_pct  = 70.0
        optimized_kw = round(q_total * frac / 1000, 3)
        log.append(f"! PRIORITY 1 — CORROSION PREVENTION")
        log.append(f"  Internal {t.internal_temp:.1f}C is only {t.internal_temp - dew_pt:.1f}C above dew point {dew_pt:.1f}C.")
        log.append(f"  Running fans at 30% to circulate air and prevent hull condensation.")
        log.append(f"  Corrosion on steel hull can cost owners $2M+ in repairs.")
        warnings.append(
            f"CORROSION RISK: Internal {t.internal_temp:.1f}C is near dew point {dew_pt:.1f}C. "
            "Fan circulation active at 30%."
        )

    # Priority 2: Mold Alert (high humidity, empty cabin)
    elif ext_rh > mkt["max_rh"] and not t.occupancy:
        mode         = HVACMode.MOLD_ALERT
        frac         = 0.35
        actual_sp    = t.target_temp
        savings_pct  = 65.0
        optimized_kw = round(q_total * frac / 1000, 3)
        log.append(f"! PRIORITY 2 — MOLD ALERT")
        log.append(f"  RH {ext_rh:.0f}% exceeds {mkt['max_rh']:.0f}% threshold for {t.market_segment}.")
        log.append(f"  Empty cabin + high humidity = mold growth risk.")
        log.append(f"  Dehumidification cycle activated at 35% load.")
        warnings.append(
            f"MOLD ALERT: Humidity {ext_rh:.0f}% > {mkt['max_rh']:.0f}% threshold. "
            "Dehumidification active."
        )

    # Priority 3: Ghost Cooling (empty, no asset risks)
    elif not t.occupancy:
        frac = mkt["ghost_frac"]
        if t.heat_soaked_hull and t.engine_adjacent:
            frac = min(0.50, frac + 0.10)
            log.append("  Compounding: hull soaked + engine adjacent -> frac raised to 50%.")
        elif t.ceiling_exposed_to_sun and t.heat_source_below:
            frac = min(0.48, frac + 0.08)
            log.append("  Compounding: hot ceiling + hot floor -> frac raised to 48%.")
        elif t.heat_soaked_hull or t.engine_adjacent or t.ceiling_exposed_to_sun or t.heat_source_below:
            frac = min(0.45, frac + 0.05)
            log.append("  Single structural factor -> frac raised to 45%.")

        mode         = HVACMode.MAINTENANCE_COOLING
        actual_sp    = t.target_temp + GHOST_SETPOINT_DELTA
        savings_pct  = round((1.0 - frac) * 100, 1)
        optimized_kw = round(q_total * frac / 1000, 3)
        log.append(f"  PRIORITY 3 — GHOST COOLING PROTOCOL")
        log.append(f"  PIR sensor = empty. No metabolic or equipment load.")
        log.append(f"  Running at {frac*100:.0f}% of calculated load = {optimized_kw:.3f} kW.")
        log.append(f"  Setpoint relaxed to {actual_sp:.1f}C. Energy saved: {savings_pct:.1f}%")

    # Priority 4: Heating Mode (arctic route)
    elif delta_t < 0 and q_heat_load > 0:
        mode         = HVACMode.EMERGENCY_HEAT
        actual_sp    = t.target_temp
        optimized_kw = round(q_heat_load / (COP_HEATING * 1000), 3)   # electrical input = heat / COP
        savings_pct  = 0.0
        log.append(f"  PRIORITY 4 — HEATING MODE (ARCTIC ROUTE)")
        log.append(f"  External {ext_temp:.1f}C < target {t.target_temp:.1f}C.")
        log.append(f"  Q_heat = {q_heat_load:.1f} W. COP = {COP_HEATING}.")
        log.append(f"  Electrical input required = {optimized_kw:.3f} kW.")

    # Priority 5: Occupied active cooling
    else:
        actual_sp = t.target_temp
        # Worst-case reference load for fraction calculation
        worst = (
            U_HULL_INSULATED * t.cabin_area_m2 * WALL_AREA_FACTOR * 20.0 +
            1200.0 * t.window_area_m2 * SHGC_WINDOW +
            4 * METABOLIC_W_PER_PERSON +       # assume max 4 occupants for normalisation
            t.equipment_wattage +
            ENGINE_RADIANT_W_M2 * t.cabin_area_m2 +
            THERMAL_LAG_W_M2    * t.cabin_area_m2 +
            U_ROOF_EXPOSED * t.cabin_area_m2 * (20.0 + SOL_AIR_DELTA_T) +
            U_DECK_SLAB    * t.cabin_area_m2 * 43.0
        ) * LATENT_CORRECTION
        load_frac = q_total / max(worst, 1.0)

        if load_frac >= 0.85:
            mode = HVACMode.FULL_COOLING
        elif load_frac >= 0.40:
            mode = HVACMode.REDUCED_COOLING
        else:
            mode = HVACMode.STANDBY

        optimized_kw = round(q_total / 1000, 3)
        savings_pct  = round(max(0.0, (1.0 - load_frac) * 20.0), 1)
        log.append(f"  PRIORITY 5 — ACTIVE COOLING (OCCUPIED)")
        log.append(f"  Load fraction: {load_frac:.0%} -> {mode.value}")
        log.append(f"  {t.occupant_count} occupants | {t.equipment_wattage:.0f}W equipment")
        log.append(f"  Setpoint maintained at {actual_sp:.1f}C.")

    # Failsafe override
    if weather_source in ("stale_cache", "dht22_fallback"):
        mode = HVACMode.FAILSAFE
        log.append("")
        log.append("! MODE OVERRIDE -> FAILSAFE (weather data unreliable)")
        log.append("  Holding last known setpoint until Starlink reconnects.")

    log.append("")
    log.append(f"=== FINAL: {optimized_kw:.3f} kW | {mode.value} | Saved: {savings_pct:.1f}% ===")

    # ── STEP 5: Build and return ──────────────────────────────
    return HVACDecision(
        cabin_id               = t.cabin_id,
        mode                   = mode,
        optimized_load_kw      = optimized_kw,
        setpoint_actual        = actual_sp,
        energy_saved_percent   = savings_pct,
        breakdown = HeatLoadBreakdown(
            q_transmission     = round(q_trans     / 1000, 4),
            q_solar            = round(q_solar     / 1000, 4),
            q_fenestration     = round(q_fenes     / 1000, 4),
            q_metabolic        = round(q_metabolic / 1000, 4),
            q_equipment        = round(q_equip     / 1000, 4),
            q_engine_radiant   = round(q_engine    / 1000, 4),
            q_thermal_lag      = round(q_lag       / 1000, 4),
            q_ceiling          = round(q_ceiling   / 1000, 4),
            q_floor_conduction = round(q_floor     / 1000, 4),
            q_latent           = round(q_latent    / 1000, 4),
            q_total_raw        = round(q_total     / 1000, 4),
            heating_load_kw    = round(q_heat_load / 1000, 4),
        ),
        decision_log     = log,
        warnings         = warnings,
        weather_source   = weather_source,
        data_age_seconds = data_age,
        dew_point        = round(dew_pt, 2),
        heating_load_kw  = round(q_heat_load / 1000, 4),
    )


# ─────────────────────────────────────────────────────────────
# FLEET AGGREGATION
# ─────────────────────────────────────────────────────────────

def calculate_fleet_summary(cabin_list: list[CabinTelemetry]):
    """Process all cabins and return aggregated FleetSummary."""
    from schemas import FleetSummary

    decisions = [calculate_optimized_load(c) for c in cabin_list]

    total   = sum(d.optimized_load_kw    for d in decisions)
    base    = sum(d.breakdown.q_total_raw for d in decisions)
    occ     = sum(1 for c in cabin_list if c.occupancy)
    ghost   = sum(1 for d in decisions if d.mode == HVACMode.MAINTENANCE_COOLING)
    corr    = sum(1 for d in decisions if d.mode == HVACMode.CORROSION_PREVENTION)
    mold    = sum(1 for d in decisions if d.mode == HVACMode.MOLD_ALERT)
    heat    = sum(1 for d in decisions if d.mode == HVACMode.EMERGENCY_HEAT)
    savings = round((1.0 - total / max(base, 0.001)) * 100, 1) if base > 0 else 0.0

    return FleetSummary(
        total_cabins          = len(decisions),
        occupied_cabins       = occ,
        ghost_cooling_cabins  = ghost,
        corrosion_risk_cabins = corr,
        mold_risk_cabins      = mold,
        heating_mode_cabins   = heat,
        total_load_kw         = round(total, 3),
        baseline_load_kw      = round(base, 3),
        fleet_savings_percent = savings,
        cabins                = decisions,
    )