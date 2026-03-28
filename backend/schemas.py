from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

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

class CabinTelemetry(BaseModel):
    cabin_id       : str
    market_segment : str = "cargo"
    occupancy      : bool
    occupant_count : int = Field(default=1, ge=0, le=100)
    internal_temp     : float = Field(..., ge=-10.0, le=60.0)
    internal_humidity : float = Field(default=60.0, ge=0.0, le=100.0)
    external_temp     : Optional[float] = None
    solar_irradiance  : Optional[float] = None
    cabin_area_m2  : float = Field(default=25.0, ge=0.0, le=2000.0)
    ship_length_m  : float = Field(default=100.0, ge=0.0, le=500.0)
    window_area_m2 : float = Field(default=1.5, ge=0.0, le=50.0)
    equipment_wattage : float = Field(default=450.0, ge=0.0, le=10000.0)
    direct_sunlight   : bool = False
    heat_soaked_hull  : bool = False
    engine_adjacent   : bool = False
    cabin_side        : CabinSide = CabinSide.INTERIOR
    ceiling_area_exposed_m2 : float = 0.0
    floor_area_exposed_m2   : float = 0.0
    target_temp : float = Field(default=22.0, ge=16.0, le=30.0)

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
    dew_point               : Optional[float] = None
    # ROI FIELDS
    money_saved_hr_inr      : float = 0.0
    co2_saved_hr_kg         : float = 0.0
    annual_roi_inr          : float = 0.0

class FleetSummary(BaseModel):
    total_cabins          : int
    occupied_cabins       : int
    total_load_kw         : float
    total_annual_savings_inr : float = 0.0
    total_annual_co2_tons    : float = 0.0
    cabins                   : list[HVACDecision] # Python 3.12 compatibility

class WeatherCache(BaseModel):
    temperature: float; humidity: float; solar_irradiance: float; timestamp: float; source: str

class WasteHeatInput(BaseModel):
    exhaust_temp_c: float; ambient_temp_c: float; exhaust_flow_kg_s: float; recovery_efficiency: float

class WasteHeatResult(BaseModel):
    gross_heat_kw: float; recoverable_kw: float; hvac_offset_kw: float; co2_saved_kg_per_hr: float; log_lines: List[str]

class DrawingParseResult(BaseModel):
    success: bool; cabin_id: str; cabin_area_m2: Optional[float]; window_area_m2: Optional[float]; parse_notes: List[str]