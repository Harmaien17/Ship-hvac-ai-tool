"""
Ship HVAC Heat Load Calculator
================================
All formulas follow ASHRAE Heat Balance Method
with marine-specific corrections.
"""

def q_solar(glass_area_m2, SHGC, irradiance_W_m2):
    """Solar heat gain through windows/portholes.
    Formula: Q = A x SHGC x I_solar
    Returns: watts"""
    return glass_area_m2 * SHGC * irradiance_W_m2

def q_conduction(U_value, area_m2, delta_T, marine_factor=1.15):
    """Heat gain through walls, roof, deck.
    Formula: Q = U x A x dT x marine_factor
    Returns: watts"""
    return U_value * area_m2 * delta_T * marine_factor

def q_people(num_people, activity="seated"):
    """Heat from human occupants (sensible + latent).
    Returns: (sensible_watts, latent_watts)"""
    rates = {
        "sleeping": (45, 35),
        "seated":   (75, 55),
        "standing": (90, 65),
        "active":   (140, 150),
        "engine_crew": (180, 110),
    }
    sens, lat = rates.get(activity, (75, 55))
    return num_people * sens, num_people * lat

def q_equipment(watts_rated, CLF=0.9, use_factor=1.0):
    """Heat from lights and machinery.
    Returns: watts"""
    return watts_rated * CLF * use_factor

def q_fresh_air(CFM, outside_temp_C, inside_temp_C=22):
    """Sensible heat from fresh outside air.
    Returns: watts"""
    delta_T = outside_temp_C - inside_temp_C
    return 1.1 * CFM * delta_T * 0.293

def calculate_airflow_CFM(total_watts, supply_temp_C=14, room_temp_C=22):
    """How much air the AC needs to move.
    Returns: CFM and CMH"""
    delta_T = room_temp_C - supply_temp_C
    CFM = total_watts / (1.1 * delta_T * 0.293)
    CMH = CFM * 1.699
    return round(CFM, 1), round(CMH, 1)

def convert_units(total_watts):
    """Convert watts to TR, kW, and BTU/hr.
    Returns: dict with all 3 units"""
    return {
        "watts":   round(total_watts, 1),
        "kW":      round(total_watts / 1000, 3),
        "TR":      round(total_watts / 3517, 3),
        "BTU_hr":  round(total_watts * 3.412, 1),
    }

def calculate_total_load(inputs: dict) -> dict:
    """Main function — runs all calculations.
    Returns complete results with breakdown."""
    solar   = q_solar(inputs["glass_area"], inputs["SHGC"], inputs["irradiance"])
    cond    = q_conduction(inputs["U_value"], inputs["wall_area"], inputs["delta_T"])
    sens, lat = q_people(inputs["num_people"], inputs.get("activity", "seated"))
    equip   = q_equipment(inputs["equipment_watts"])
    fresh   = q_fresh_air(inputs["fresh_air_CFM"], inputs["outside_temp"])
    subtotal = solar + cond + sens + lat + equip + fresh
    total   = subtotal * 1.15
    CFM, CMH = calculate_airflow_CFM(total)
    return {
        "breakdown": {"solar":solar,"conduction":cond,"people_sens":sens,"people_lat":lat,"equipment":equip,"fresh_air":fresh},
        "total": convert_units(total),
        "airflow": {"CFM": CFM, "CMH": CMH},
    }

# ── Quick test — run: python backend/hvac_engine.py ──────────
if __name__ == "__main__":
    test_cabin = {
        "glass_area":      0.5,    # m2  — one porthole
        "SHGC":            0.6,    # single glazing
        "irradiance":      950,   # W/m2 — Indian Ocean July
        "U_value":         0.7,    # W/m2K — 50mm insulation
        "wall_area":       32,    # m2 — total exposed walls
        "delta_T":         16,    # outside 38C, inside 22C
        "num_people":      2,     # two passengers
        "activity":        "seated",
        "equipment_watts": 150,   # lights + TV
        "fresh_air_CFM":   40,    # ASHRAE min for 2 persons
        "outside_temp":    38,    # degrees C
    }
    result = calculate_total_load(test_cabin)
    print("=== CABIN RESULT ===")
    print(f"TR  : {result['total']['TR']} tons of refrigeration")
    print(f"kW  : {result['total']['kW']} kilowatts")
    print(f"BTU : {result['total']['BTU_hr']} BTU/hr")
    print(f"CFM : {result['airflow']['CFM']} cubic feet/min")
    print(f"CMH : {result['airflow']['CMH']} cubic metres/hr")
    print("\nBreakdown:")
    for k, v in result["breakdown"].items():
        print(f"  {k:15s}: {round(v,1):8.1f} W")