from pydantic import BaseModel, Field
from typing import Optional, Dict

# ── What the user sends TO the API ───────────────────────────
class RoomInput(BaseModel):
    # Space geometry
    glass_area:       float = Field(0.5,  description="Glass/porthole area in m2",         ge=0)
    SHGC:             float = Field(0.6,  description="Solar Heat Gain Coefficient 0-1",    ge=0, le=1)
    irradiance:       float = Field(950, description="Solar irradiance W/m2",               ge=0)
    U_value:          float = Field(0.7,  description="Wall U-value W/m2K",                ge=0.1)
    wall_area:        float = Field(32,  description="Total exposed wall area m2",         ge=1)
    delta_T:          float = Field(16,  description="Outside minus inside temperature C",  ge=0)
    # Occupancy
    num_people:       int   = Field(2,   description="Number of occupants",               ge=0)
    activity:         str   = Field("seated", description="sleeping/seated/standing/active/engine_crew")
    # Equipment
    equipment_watts:  float = Field(150, description="Lights + equipment total watts",      ge=0)
    # Ventilation
    fresh_air_CFM:    float = Field(40,  description="Fresh outside air in CFM",            ge=0)
    outside_temp:     float = Field(38,  description="Outside air temperature C")
    # Optional ship info
    ship_type:        Optional[str]   = Field("cruise", description="cargo/cruise/naval/tanker")
    space_type:       Optional[str]   = Field("cabin",  description="cabin/engine_room/bridge/galley")
    room_name:        Optional[str]   = Field("Cabin 1",description="Label for this room")

# ── What the API sends BACK ───────────────────────────────────
class LoadResult(BaseModel):
    watts:   float
    kW:      float
    TR:      float
    BTU_hr:  float

class AirflowResult(BaseModel):
    CFM: float
    CMH: float

class CalculationResponse(BaseModel):
    room_name:  str
    total:      LoadResult
    airflow:    AirflowResult
    breakdown:  Dict[str, float]
    status:     str = "success"

# ── Weather response ──────────────────────────────────────────
class WeatherResponse(BaseModel):
    temperature_C:  float
    humidity_pct:   float
    description:    str
    city:           str
    status:         str = "success"