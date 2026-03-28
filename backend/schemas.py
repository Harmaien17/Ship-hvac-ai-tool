"""
MAR-HVAC AI — Pydantic Data Models
backend/schemas.py
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum

# --- ENUMS ---
class CabinSide(str, Enum):
    STARBOARD = "starboard"
    PORT      = "port"
    INTERIOR  = "interior"
    BOW       = "bow"
    STERN     = "stern"

class HVACMode(str, Enum):
    FULL_COOLING          = "FULL_COOLING"
    REDUCED_COOLING       = "REDUCED_COOLING"
    STANDBY               = "STANDBY"
    MAINTENANCE_COOLING   = "MAINTENANCE_COOLING"
    EMERGENCY_HEAT        = "EMERGENCY_HEAT"
    CORROSION_PREVENTION  = "CORROSION_PREVENTION"
    MOLD_ALERT            = "MOLD_ALERT"
    FAILSAFE              = "FAILSAFE"

# --- INPUT MODELS ---
class CabinTelemetry(BaseModel):
    cabin_id       : str
    market_segment : str = "cargo"
    occupancy      : bool
    
    # REQUIREMENT 1: Number of people
    occupant_count : int = Field(default=1, ge=0, le=100)
    
    internal_temp     : float = Field(..., ge=-10.0, le=60.0)
    internal_humidity : float = Field(default=60.0, ge=0.0, le=100.0)
    external_temp     : Optional[float] = Field(default=None, ge=-30.0, le=60.0)
    solar_irradiance  : Optional[float] = Field(default=None, ge=0.0, le=1200.0)
    
    # REQUIREMENT 6: Area up to 2000m2
    cabin_area_m2  : float = Field(default=20.0, ge=0.0, le=2000.0)
    
    # REQUIREMENT 7: Ship Length
    ship_length_m  : float = Field(default=100.0, ge=0.0, le=500.0)
    
    # REQUIREMENT 2: Window Area
    window_area_m2 : float = Field(default=0.12, ge=0.0, le=50.0)
    
    # REQUIREMENT 3: Equipment Wattage
    equipment_wattage : float = Field(default=120.0, ge=0.0, le=10000.0)
    
    direct_sunlight   : bool      = False
    heat_soaked_hull  : bool      = False
    engine_adjacent   : bool      = False
    cabin_side        : CabinSide = CabinSide.INTERIOR
    
    # REQUIREMENT 4 & 5: Ceiling and Floor areas
    ceiling_area_exposed_m2 : float = Field(default=0.0, ge=0.0, le=2000.0)
    floor_area_exposed_m2   : float = Field(default=0.0, ge=0.0, le=2000.0)
    
    target_temp : float = Field(default=22.0, ge=16.0, le=30.0)

    @field_validator("internal_temp")
    @classmethod
    def temp_sanity(cls, v):
        if v > 50: raise ValueError("Internal temp > 50C - sensor risk.")
        return round(v, 2)

# --- OUTPUT MODELS ---
class HeatLoadBreakdown(BaseModel):
    q_transmission     : float
    q_solar            : float
    q_engine_radiant   : float
    q_thermal_lag      : float
    q_latent           : float
    q_metabolic        : float
    q_equipment        : float
    q_fenestration     : float
    q_ceiling          : float
    q_floor_conduction : float
    q_total_raw        : float
    heating_load_kw    : float = 0.0

class HVACDecision(BaseModel):
    cabin_id                : str
    mode                    : HVACMode
    optimized_load_kw       : float
    setpoint_actual         : float
    energy_saved_percent    : float
    breakdown               : HeatLoadBreakdown
    decision_log            : List[str]
    warnings                : List[str] = []
    weather_source          : str
    data_age_seconds        : Optional[float] = None
    dew_point               : Optional[float] = None
    waste_heat_recovered_kw : float = 0.0
    heating_load_kw         : float = 0.0

# --- FLEET MODELS ---
class FleetSummary(BaseModel):
    total_cabins          : int
    occupied_cabins       : int
    ghost_cooling_cabins  : int
    corrosion_risk_cabins : int = 0
    mold_risk_cabins      : int = 0
    heating_mode_cabins   : int = 0
    total_load_kw         : float
    baseline_load_kw      : float
    fleet_savings_percent : float
    cabins                : List[HVACDecision]

# --- OTHER MODELS ---
class WeatherCache(BaseModel):
    temperature      : float
    humidity         : float
    solar_irradiance : float = 400.0
    timestamp        : float
    source           : str = "openweather_api"

class WasteHeatInput(BaseModel):
    exhaust_temp_c    : float = Field(default=380.0, ge=50.0, le=800.0)
    ambient_temp_c    : float = Field(default=30.0, ge=-30.0, le=55.0)
    exhaust_flow_kg_s : float = Field(default=2.5, ge=0.1, le=100.0)
    recovery_efficiency: float = Field(default=0.35, ge=0.0, le=1.0)

class WasteHeatResult(BaseModel):
    gross_heat_kw       : float
    recoverable_kw      : float
    hvac_offset_kw      : float
    co2_saved_kg_per_hr : float
    log_lines           : List[str]

class DrawingParseResult(BaseModel):
    success           : bool
    cabin_id          : str = "PARSED-CABIN"
    cabin_area_m2     : Optional[float] = None
    window_area_m2    : Optional[float] = None
    ceiling_height_m  : Optional[float] = None
    wall_material     : Optional[str]   = None
    u_value_override  : Optional[float] = None
    raw_text_snippet  : str = ""
    parse_notes       : List[str] = []