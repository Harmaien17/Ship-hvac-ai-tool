"""
MAR-HVAC AI — Pydantic Data Models
backend/schemas.py

Updated: Week 4 + 5 + 6
  - 5 new CabinTelemetry fields (occupant_count, window_area_m2,
    equipment_wattage, ceiling_exposed_to_sun, heat_source_below)
  - HeatLoadBreakdown now has q_ceiling, q_floor_conduction, q_fenestration,
    q_metabolic, q_equipment as separate line items
  - HVACDecision now has waste_heat_recovered_kw + heating_load_kw
  - FleetSummary now has mold_risk_cabins + heating_mode_cabins
  - New models: WasteHeatResult, DrawingParseResult (Weeks 5 & 6)

YOU are the only one who edits this file.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class CabinSide(str, Enum):
    STARBOARD = "starboard"   # Right side — morning sun
    PORT      = "port"        # Left side — afternoon sun
    INTERIOR  = "interior"    # No direct hull exposure
    BOW       = "bow"         # Forward-facing
    STERN     = "stern"       # Aft — near engine


class HVACMode(str, Enum):
    # ── Cooling modes ──────────────────────────────────────
    FULL_COOLING          = "FULL_COOLING"           # Occupied, high external heat
    REDUCED_COOLING       = "REDUCED_COOLING"        # Occupied, moderate load
    STANDBY               = "STANDBY"                # Near-ambient, minimal run
    # ── Ghost Cooling / empty cabin ────────────────────────
    MAINTENANCE_COOLING   = "MAINTENANCE_COOLING"    # Ghost protocol — 40% load
    # ── Heating ────────────────────────────────────────────
    EMERGENCY_HEAT        = "EMERGENCY_HEAT"         # Arctic route, ext < target
    # ── Asset Defence ──────────────────────────────────────
    CORROSION_PREVENTION  = "CORROSION_PREVENTION"   # Dew point breach imminent
    MOLD_ALERT            = "MOLD_ALERT"             # RH too high for too long
    # ── Fail-safe ──────────────────────────────────────────
    FAILSAFE              = "FAILSAFE"               # No weather data, hold setpoint


# ─────────────────────────────────────────────
# INPUT — CABIN TELEMETRY
# ─────────────────────────────────────────────

class CabinTelemetry(BaseModel):
    """
    Real-time telemetry for one cabin.

    Data sources:
      PIR sensor       -> occupancy
      DHT22 sensor     -> internal_temp, internal_humidity
      OpenWeather API  -> external_temp, solar_irradiance
      Manual / AutoCAD -> cabin_area_m2, window_area_m2, occupant_count, etc.
      Toggles          -> direct_sunlight, heat_soaked_hull, engine_adjacent,
                          ceiling_exposed_to_sun, heat_source_below
    """

    # ── Identity ──────────────────────────────────────────
    cabin_id       : str
    market_segment : str = "cargo"   # cargo | cruise | navy | hospital | yacht

    # ── Occupancy ─────────────────────────────────────────
    occupancy      : bool   # PIR motion sensor — True if cabin is occupied

    # NEW FIELD 1: exact number of people instead of just occupied/empty
    # Used for accurate metabolic heat: Q_metabolic = N * 75W
    occupant_count : int = Field(
        default=1, ge=0, le=50,
        description="Number of occupants detected or expected. 0 = empty cabin."
    )

    # ── DHT22 sensor readings ─────────────────────────────
    internal_temp     : float = Field(..., ge=-10.0, le=60.0,
        description="DHT22 internal cabin temperature in degrees C")
    internal_humidity : float = Field(default=60.0, ge=0.0, le=100.0,
        description="DHT22 relative humidity inside cabin in percent")

    # ── External conditions (from OpenWeather API) ────────
    external_temp     : Optional[float] = Field(default=None, ge=-30.0, le=60.0,
        description="External air temperature in degrees C. None triggers fail-safe chain.")
    solar_irradiance  : Optional[float] = Field(default=None, ge=0.0, le=1200.0,
        description="Solar irradiance in W/m2 from OpenWeather API.")

    # ── Geometry ──────────────────────────────────────────
    cabin_area_m2  : float = Field(default=20.0, ge=5.0, le=200.0,
        description="Cabin floor area in m2. Auto-filled from AutoCAD parser in Week 6.")

    # NEW FIELD 2: actual glass/window area for fenestration solar gain
    # More accurate than the old fixed PORTHOLE_AREA_M2 constant
    # ASHRAE: Q_fenestration = I_solar * A_window * SHGC
    window_area_m2 : float = Field(default=0.12, ge=0.0, le=10.0,
        description="Total glazed area (portholes + windows) in m2. Default = standard porthole.")

    # NEW FIELD 3: manual equipment wattage override
    # Overrides the default EQUIPMENT_LOAD_W constant (120W)
    # Useful for galleys (stoves), server rooms, or luxury suites with extra electronics
    equipment_wattage : float = Field(default=120.0, ge=0.0, le=5000.0,
        description="Total equipment heat load in Watts. Overrides default 120W constant.")

    # ── Ship dynamics toggles ─────────────────────────────
    direct_sunlight   : bool      = False
    heat_soaked_hull  : bool      = False
    engine_adjacent   : bool      = False
    cabin_side        : CabinSide = CabinSide.INTERIOR

    # NEW FIELD 4: ceiling directly under open sun deck / hot roof
    # If True, solar load is also applied to ceiling area, not just windows
    # ASHRAE: Q_ceiling = I_solar * A_ceiling * U_roof * delta_T_sol-air
    ceiling_exposed_to_sun : bool = Field(default=False,
        description="True if cabin ceiling is under a sun-exposed deck. Adds solar-air load to roof.")

    # NEW FIELD 5: cabin is directly above a heat source (generator room, boiler)
    # Similar to engine_adjacent but applied to the floor slab instead of wall bulkhead
    # Q_floor = U_slab * A_floor * (T_source - T_cabin)
    heat_source_below : bool = Field(default=False,
        description="True if cabin floor is above a high-heat space (generator room, boiler). Adds floor conduction.")

    # ── Setpoint ──────────────────────────────────────────
    target_temp : float = Field(default=22.0, ge=16.0, le=30.0,
        description="Desired cabin temperature in degrees C. ASHRAE comfort: 20-24C.")

    # ── Validators ────────────────────────────────────────
    @field_validator("internal_temp")
    @classmethod
    def temp_sanity(cls, v):
        if v > 45:
            raise ValueError("Internal temp >45C — sensor may be faulty or fire risk.")
        return round(v, 2)

    @field_validator("external_temp")
    @classmethod
    def ext_temp_round(cls, v):
        return round(v, 2) if v is not None else None

    @field_validator("occupant_count")
    @classmethod
    def occupant_consistency(cls, v, info):
        # If occupancy is False (PIR = empty), occupant_count must be 0
        # Pydantic v2: use info.data to access other already-validated fields
        data = info.data if hasattr(info, "data") else {}
        if data.get("occupancy") is False:
            return 0
        return v


# ─────────────────────────────────────────────
# CACHE MODELS
# ─────────────────────────────────────────────

class WeatherCache(BaseModel):
    """Short-term 1-hour in-memory weather cache."""
    temperature      : float
    humidity         : float
    solar_irradiance : float = 400.0
    timestamp        : float   # Unix timestamp of last successful fetch
    source           : str = "openweather_api"


class ForecastPoint(BaseModel):
    """One data point in the 7-day Starlink forecast buffer."""
    timestamp  : float
    temp       : float
    humidity   : float
    description: str = ""


# ─────────────────────────────────────────────
# OUTPUT — HEAT LOAD BREAKDOWN
# ─────────────────────────────────────────────

class HeatLoadBreakdown(BaseModel):
    """
    Fully decomposed heat load in kW.

    Each line = one physical heat source.
    This is displayed in:
      - The AI Decision Log (terminal text)
      - The Plotly horizontal bar chart (visual)
      - The /optimize API response (for auditing)

    New in Week 4:
      q_metabolic        — metabolic heat from N occupants (N * 75W)
      q_equipment        — electronics load (from equipment_wattage field)
      q_fenestration     — solar gain through windows (I * A_window * SHGC)
      q_ceiling          — solar-air load through roof (ceiling_exposed_to_sun)
      q_floor_conduction — heat from generator/boiler room below (heat_source_below)
    """

    # ── Existing components ───────────────────────────────
    q_transmission     : float   # Wall/hull conduction: U * A_wall * deltaT (kW)
    q_solar            : float   # Porthole solar: I * A_porthole * SHGC (kW)
    q_engine_radiant   : float   # Engine room radiant through bulkhead (kW)
    q_thermal_lag      : float   # Delayed hull heat release (kW)
    q_latent           : float   # Salt-air latent heat correction (kW)

    # ── NEW: separated internal loads ─────────────────────
    q_metabolic        : float   # N_occupants * 75W metabolic heat (kW)
    q_equipment        : float   # equipment_wattage field (kW)

    # ── NEW: fenestration (replaces old q_solar porthole) ─
    # q_solar above = porthole only; q_fenestration = all glazed area
    q_fenestration     : float   # I_solar * window_area_m2 * SHGC (kW)

    # ── NEW: ceiling and floor loads ──────────────────────
    q_ceiling          : float   # Solar-air load through sun-exposed roof (kW)
    q_floor_conduction : float   # Conduction from heat source below floor (kW)

    # ── Waste heat (Week 5) ───────────────────────────────
    q_waste_heat_saved : float = 0.0   # Heat recovered from engine exhaust (kW)

    # ── Total ─────────────────────────────────────────────
    q_total_raw        : float   # Sum of all above before AI optimisation (kW)

    # ── Heating mode ──────────────────────────────────────
    heating_load_kw    : float = 0.0   # Set when EMERGENCY_HEAT mode active


# ─────────────────────────────────────────────
# OUTPUT — HVAC DECISION
# ─────────────────────────────────────────────

class HVACDecision(BaseModel):
    """
    Full AI engine output for one cabin.
    Contains optimised load, mode, reasoning log, and all intermediate values.
    """
    cabin_id                  : str
    mode                      : HVACMode
    optimized_load_kw         : float
    setpoint_actual           : float
    energy_saved_percent      : float = Field(ge=0.0, le=100.0)
    breakdown                 : HeatLoadBreakdown
    decision_log              : list[str]
    warnings                  : list[str] = []
    weather_source            : str   # api_live | cache | stale_cache | dht22_fallback
    data_age_seconds          : Optional[float] = None
    dew_point                 : Optional[float] = None

    # Week 5 additions
    waste_heat_recovered_kw   : float = 0.0
    heating_load_kw           : float = 0.0


# ─────────────────────────────────────────────
# OUTPUT — FLEET SUMMARY
# ─────────────────────────────────────────────

class FleetSummary(BaseModel):
    """Aggregated status across all cabins for the fleet panel."""
    total_cabins          : int
    occupied_cabins       : int
    ghost_cooling_cabins  : int
    corrosion_risk_cabins : int = 0
    mold_risk_cabins      : int = 0      # Week 4
    heating_mode_cabins   : int = 0      # Week 4
    total_load_kw         : float
    baseline_load_kw      : float
    fleet_savings_percent : float
    total_waste_heat_kw   : float = 0.0  # Week 5
    cabins                : list[HVACDecision]


# ─────────────────────────────────────────────
# WEEK 5 — WASTE HEAT MODEL
# ─────────────────────────────────────────────

class WasteHeatInput(BaseModel):
    """Input for the waste heat recovery calculator."""
    exhaust_temp_c    : float = Field(default=380.0, ge=50.0, le=800.0,
        description="Engine exhaust gas temperature in degrees C. Typical marine diesel: 300-450C.")
    ambient_temp_c    : float = Field(default=30.0, ge=-30.0, le=55.0,
        description="Ambient air temperature in degrees C.")
    exhaust_flow_kg_s : float = Field(default=2.5, ge=0.1, le=100.0,
        description="Mass flow rate of exhaust gas in kg/s.")
    recovery_efficiency: float = Field(default=0.35, ge=0.0, le=1.0,
        description="Heat exchanger efficiency. 0.35 is conservative for marine HRSGs.")


class WasteHeatResult(BaseModel):
    """Output from the waste heat recovery calculator."""
    gross_heat_kw       : float   # Total heat in exhaust: m_dot * Cp * delta_T
    recoverable_kw      : float   # After efficiency: gross * efficiency
    hvac_offset_kw      : float   # How much this reduces HVAC compressor demand
    co2_saved_kg_per_hr : float   # Emissions saved
    log_lines           : list[str]


# ─────────────────────────────────────────────
# WEEK 6 — AUTOCAD PARSER MODEL
# ─────────────────────────────────────────────

class DrawingParseResult(BaseModel):
    """Result from parsing a ship drawing PDF."""
    success           : bool
    cabin_id          : str = "PARSED-CABIN"
    cabin_area_m2     : Optional[float] = None
    window_area_m2    : Optional[float] = None
    ceiling_height_m  : Optional[float] = None
    wall_material     : Optional[str]   = None
    u_value_override  : Optional[float] = None
    raw_text_snippet  : str = ""
    parse_notes       : list[str] = []