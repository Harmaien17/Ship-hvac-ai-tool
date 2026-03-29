"""
MAR-HVAC AI — ROI & Carbon Calculator
backend/economics.py
"""

# Industry Standards for 2026 Marine Operations
FUEL_COST_PER_KWH_INR = 14.20  
CO2_KG_PER_KWH = 0.68          
SHIP_OPERATIONAL_HOURS = 8000  

def calculate_roi_metrics(optimized_kw: float):
    """
    Calculates Financial and Environmental impact.
    Assumes a 1.5x baseline load for comparison.
    """
    baseline_kw = optimized_kw * 1.5
    saved_kw = max(0.0, baseline_kw - optimized_kw)
    
    money_saved_hr = saved_kw * FUEL_COST_PER_KWH_INR
    co2_saved_hr = saved_kw * CO2_KG_PER_KWH
    
    annual_savings_inr = money_saved_hr * SHIP_OPERATIONAL_HOURS
    # Convert annual CO2 to Tons
    annual_co2_tons = (co2_saved_hr * SHIP_OPERATIONAL_HOURS) / 1000
    
    return {
        "hourly_inr": round(money_saved_hr, 2),
        "hourly_co2_kg": round(co2_saved_hr, 2),
        "annual_savings_inr": round(annual_savings_inr, 2),
        "annual_co2_tons": round(annual_co2_tons, 2)
    }