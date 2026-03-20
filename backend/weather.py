import requests
import os
from dotenv import load_dotenv

load_dotenv()   # reads your .env file

API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

def get_weather_by_coords(lat: float, lon: float) -> dict:
    """Fetch current weather for a lat/lon position (ship at sea)."""
    if not API_KEY:
        # No API key — return tropical defaults so app still works
        return {
            "temperature_C": 35.0,
            "humidity_pct":  85.0,
            "description":   "API key not set — using tropical defaults",
            "city":          f"Position {lat:.2f}, {lon:.2f}",
        }
    try:
        params = {
            "lat":   lat,
            "lon":   lon,
            "appid": API_KEY,
            "units": "metric",   # gives Celsius directly
        }
        r = requests.get(BASE_URL, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        return {
            "temperature_C": round(data["main"]["temp"], 1),
            "humidity_pct":  round(data["main"]["humidity"], 1),
            "description":   data["weather"][0]["description"].capitalize(),
            "city":          data.get("name", f"At sea {lat:.2f}N {lon:.2f}E"),
        }
    except requests.exceptions.RequestException as e:
        return {
            "temperature_C": 35.0,
            "humidity_pct":  85.0,
            "description":   f"Weather fetch failed: {str(e)}",
            "city":          "Fallback data",
        }

def get_weather_by_city(city: str) -> dict:
    """Fetch weather by city name — useful for port cities."""
    if not API_KEY:
        return {"temperature_C":32.0,"humidity_pct":80.0,"description":"No API key","city":city}
    try:
        r = requests.get(BASE_URL, params={"q":city,"appid":API_KEY,"units":"metric"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        return {
            "temperature_C": round(data["main"]["temp"], 1),
            "humidity_pct":  round(data["main"]["humidity"], 1),
            "description":   data["weather"][0]["description"].capitalize(),
            "city":          data.get("name", city),
        }
    except:
        return {"temperature_C":32.0,"humidity_pct":80.0,"description":"Fetch failed","city":city}

# Quick test
if __name__ == "__main__":
    result = get_weather_by_city("Mumbai")
    print("Mumbai weather:", result)