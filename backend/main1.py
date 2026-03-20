from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from backend.hvac_engine import calculate_total_load
from backend.weather import get_weather_by_coords, get_weather_by_city
from backend.schemas import RoomInput, CalculationResponse, WeatherResponse

# ── Create the FastAPI app ─────────────────────────────────────
app = FastAPI(
    title="Ship HVAC AI Tool",
    description="Marine heat load calculator — ASHRAE method with IMO marine factors",
    version="1.0.0",
)

# ── Allow frontend to talk to backend (CORS) ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # allow all origins during development
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════
# ENDPOINT 1 — Health check
# Visit: http://127.0.0.1:8000/api/health
# ══════════════════════════════════════════════════════════════
@app.get("/api/health")
def health_check():
    return {"status": "Ship HVAC API is running", "version": "1.0.0"}

# ══════════════════════════════════════════════════════════════
# ENDPOINT 2 — Main calculation
# POST: http://127.0.0.1:8000/api/calculate
# Body: JSON with room inputs (see RoomInput schema)
# ══════════════════════════════════════════════════════════════
@app.post("/api/calculate", response_model=CalculationResponse)
def calculate(room: RoomInput):
    try:
        inputs = {
            "glass_area":      room.glass_area,
            "SHGC":            room.SHGC,
            "irradiance":      room.irradiance,
            "U_value":         room.U_value,
            "wall_area":       room.wall_area,
            "delta_T":         room.delta_T,
            "num_people":      room.num_people,
            "activity":        room.activity,
            "equipment_watts": room.equipment_watts,
            "fresh_air_CFM":   room.fresh_air_CFM,
            "outside_temp":    room.outside_temp,
        }
        result = calculate_total_load(inputs)
        return CalculationResponse(
            room_name = room.room_name or "Room",
            total     = result["total"],
            airflow   = result["airflow"],
            breakdown = result["breakdown"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════
# ENDPOINT 3 — Weather by coordinates (ship GPS position)
# GET: http://127.0.0.1:8000/api/weather/19.076/72.877
# (Mumbai coords example)
# ══════════════════════════════════════════════════════════════
@app.get("/api/weather/{lat}/{lon}", response_model=WeatherResponse)
def weather_by_coords(lat: float, lon: float):
    data = get_weather_by_coords(lat, lon)
    return WeatherResponse(**data)

# ══════════════════════════════════════════════════════════════
# ENDPOINT 4 — Weather by city name
# GET: http://127.0.0.1:8000/api/weather/city/Mumbai
# ══════════════════════════════════════════════════════════════
@app.get("/api/weather/city/{city_name}", response_model=WeatherResponse)
def weather_by_city(city_name: str):
    data = get_weather_by_city(city_name)
    return WeatherResponse(**data)