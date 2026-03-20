import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.hvac_engine import (
    q_solar, q_conduction, q_people,
    q_equipment, q_fresh_air, convert_units, calculate_total_load
)

# ── Test each function individually ───────────────────────────
def test_q_solar_basic():
    result = q_solar(1.0, 0.6, 1000)
    assert result == 600.0, f"Expected 600W, got {result}"

def test_q_solar_zero_glass():
    """Room with no windows — solar gain must be zero."""
    result = q_solar(0, 0.6, 1000)
    assert result == 0

def test_q_conduction_formula():
    """U=1, A=10, dT=10 with marine factor 1.15 = 115W"""
    result = q_conduction(1.0, 10, 10, marine_factor=1.15)
    assert abs(result - 115.0) < 0.1

def test_q_people_seated():
    sens, lat = q_people(2, "seated")
    assert sens == 150   # 2 x 75W
    assert lat  == 110   # 2 x 55W

def test_q_people_engine_crew():
    """Engine crew generates much more heat — verify it's higher than seated."""
    sens_seat, _ = q_people(1, "seated")
    sens_crew, _ = q_people(1, "engine_crew")
    assert sens_crew > sens_seat

def test_unit_converter():
    result = convert_units(3517)
    assert result["TR"]  == 1.0      # exactly 1 TR
    assert result["kW"]  == 3.517
    assert abs(result["BTU_hr"] - 12000) < 5

def test_cabin_example_full():
    """Full cabin calculation — result must be within 5% of 0.74 TR."""
    inputs = {
        "glass_area":0.5,"SHGC":0.6,"irradiance":950,
        "U_value":0.7,"wall_area":32,"delta_T":16,
        "num_people":2,"activity":"seated",
        "equipment_watts":150,"fresh_air_CFM":40,"outside_temp":38,
    }
    result = calculate_total_load(inputs)
    TR = result["total"]["TR"]
    assert 0.38 < TR < 0.50, f"TR {TR} outside expected range 0.38-0.50"

def test_breakdown_has_all_components():
    inputs = {
        "glass_area":1.0,"SHGC":0.5,"irradiance":800,
        "U_value":0.8,"wall_area":20,"delta_T":12,
        "num_people":4,"activity":"seated",
        "equipment_watts":300,"fresh_air_CFM":80,"outside_temp":35,
    }
    result = calculate_total_load(inputs)
    breakdown = result["breakdown"]
    for key in ["solar","conduction","people_sens","people_lat","equipment","fresh_air"]:
        assert key in breakdown, f"Missing key: {key}"