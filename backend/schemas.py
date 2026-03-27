"""
MAR-HVAC AI — Pydantic Data Models
backend/schemas.py

All request/response shapes for the MAR-HVAC system.
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
    FULL_COOLING          = "FULL_COOLING"
    REDUCED_COOLING       = "REDUCED_COOLING"
    MAINTENANCE_COOLING   = "MAINTENANCE_COOLING"   # Ghost cooling — empty cabin
    STANDBY               = "STANDBY"
    FAILSAFE              = "FAILSAFE"              # No internet at sea
    EMERGENCY_HEAT        = "EMERGENCY_HEAT"        # Arctic route
    CORROSION_PREVENTION  = "CORROSION_PREVENTION"  # Dew point / humidity risk
    MOLD_ALERT            = "MOLD_ALERT"            # RH too high for too long


# ─────────────────────────────────────────────
# INPUT MODELS
# ─────────────────────────────────────────────

class CabinTelemetry(BaseModel):
    """
    Real-time telemetry for one cabin.
    Sources: PIR (occupancy), DHT22 (temp/humidity),
             OpenWeather API (external_temp), manual toggles.
    """

    cabin_id          : str
    occupancy         : bool                                            # PIR sensor
    internal_temp     : float = Field(..., ge=-10.0, le=60.0)         # DHT22 degrees C
    internal_humidity : float = Field(default=60.0, ge=0.0, le=100.0) # DHT22 %RH
    external_temp     : Optional[float] = Field(default=None, ge=-30.0, le=60.0)
    solar_irradiance  : Optional[float] = Field(default=None, ge=0.0, le=1200.0)

    # Ship dynamics toggles
    direct_sunlight   : bool      = False
    heat_soaked_hull  : bool      = False
    engine_adjacent   : bool      = False
    cabin_side        : CabinSide = CabinSide.INTERIOR

    # Setpoint and geometry
    target_temp       : float = Field(default=22.0, ge=16.0, le=30.0)
    cabin_area_m2     : float = Field(default=20.0, ge=5.0, le=200.0)

    # Market segment — changes thresholds per vessel type
    market_segment    : str = "cargo"   # cargo | cruise | navy | hospital | yacht

    @field_validator("internal_temp")
    @classmethod
    def temp_sanity(cls, v):
        if v > 45:
            raise ValueError("Internal temp >45 degrees — sensor may be faulty.")
        return round(v, 2)

    @field_validator("external_temp")
    @classmethod
    def ext_temp_round(cls, v):
        return round(v, 2) if v is not None else None


# ─────────────────────────────────────────────
# CACHE MODELS
# ─────────────────────────────────────────────

class WeatherCache(BaseModel):
    """Short-term weather cache — 1 hour expiry."""
    temperature      : float
    humidity         : float
    solar_irradiance : float = 400.0
    timestamp        : float   # Unix timestamp of last successful fetch
    source           : str = "openweather_api"


class ForecastPoint(BaseModel):
    """Single data point in the 7-day Starlink forecast buffer."""
    timestamp  : float
    temp       : float
    humidity   : float
    description: str = ""


# ─────────────────────────────────────────────
# OUTPUT MODELS
# ─────────────────────────────────────────────

class HeatLoadBreakdown(BaseModel):
    """
    Decomposed heat load — contribution of each factor in kW.
    Shown in AI Decision Log and Plotly breakdown chart.
    """
    q_transmission    : float   # Conduction through hull/walls (kW)
    q_solar           : float   # Solar gain through portholes (kW)
    q_internal        : float   # Metabolic heat — occupants + equipment (kW)
    q_engine_radiant  : float   # Radiant heat from adjacent engine room (kW)
    q_thermal_lag     : float   # Stored heat release from heat-soaked hull (kW)
    q_latent          : float   # Latent load from salt-air humidity (kW)
    q_waste_heat_saved: float = 0.0   # Energy recovered from engine exhaust (kW)
    q_total_raw       : float   # Sum of all loads before AI optimisation (kW)


class HVACDecision(BaseModel):
    """
    Full output from the MAR-HVAC AI engine for one cabin.
    Contains the optimised load, mode, step-by-step reasoning log,
    and all intermediate calculated values.
    """
    cabin_id               : str
    mode                   : HVACMode
    optimized_load_kw      : float
    setpoint_actual        : float
    energy_saved_percent   : float = Field(ge=0.0, le=100.0)
    breakdown              : HeatLoadBreakdown
    decision_log           : list[str]
    warnings               : list[str] = []
    weather_source         : str   # 'api_live' | 'cache' | 'stale_cache' | 'dht22_fallback'
    data_age_seconds       : Optional[float] = None
    dew_point              : Optional[float] = None
    waste_heat_available_kw: float = 0.0


class FleetSummary(BaseModel):
    """Aggregated status across all cabins for the fleet overview panel."""
    total_cabins          : int
    occupied_cabins       : int
    ghost_cooling_cabins  : int
    corrosion_risk_cabins : int = 0
    total_load_kw         : float
    baseline_load_kw      : float
    fleet_savings_percent : float
    total_waste_heat_kw   : float = 0.0
    cabins                : list[HVACDecision]