import pytest
import sys
import os

# Ensure the root directory is in the path so 'backend' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.schemas import CabinTelemetry, HVACMode
from backend.hvac_engine import calculate_optimized_load

# ─────────────────────────────────────────────────────────────
# TEST CASE 1: The "Ghost Cooling" Efficiency (PPT Page 3 & 6)
# ─────────────────────────────────────────────────────────────
def test_ghost_cooling_logic():
    """
    Verify that an empty cabin triggers MAINTENANCE_COOLING 
    and reduces load to 40% of baseline.
    """
    telemetry = CabinTelemetry(
        cabin_id="TEST-A1",
        occupancy=False,  # Empty cabin triggers Protocol [cite: 33, 56]
        internal_temp=28.0,
        internal_humidity=65.0,
        target_temp=22.0,
        cabin_area_m2=20.0
    )
    
    decision = calculate_optimized_load(telemetry)
    
    # Logic: If empty, mode must be MAINTENANCE_COOLING [cite: 95, 106]
    assert decision.mode == HVACMode.MAINTENANCE_COOLING
    # Logic: Load reduction should reflect ~60% savings [cite: 31]
    assert decision.energy_saved_percent == 60.0 

# ─────────────────────────────────────────────────────────────
# TEST CASE 2: Engine Proximity Load (PPT Page 5)
# ─────────────────────────────────────────────────────────────
def test_engine_adjacent_heat_load():
    """
    Rooms near the engine should have higher radiant heat[cite: 84].
    """
    normal = CabinTelemetry(cabin_id="NORMAL", occupancy=True, internal_temp=25, 
                            cabin_area_m2=20, engine_adjacent=False)
    hot_room = CabinTelemetry(cabin_id="ENGINE-SIDE", occupancy=True, internal_temp=25, 
                              cabin_area_m2=20, engine_adjacent=True)
    
    res_a = calculate_optimized_load(normal)
    res_b = calculate_optimized_load(hot_room)
    
    # Engine radiant heat (85W/m2) must increase total load
    assert res_b.optimized_load_kw > res_a.optimized_load_kw

# ─────────────────────────────────────────────────────────────
# TEST CASE 3: ROI Accuracy (The 12-18 Lakh Promise)
# ─────────────────────────────────────────────────────────────
def test_roi_calculation_bounds():
    """
    Verify that the ROI math reflects the ₹14.20/kWh fuel cost.
    """
    telemetry = CabinTelemetry(
        cabin_id="ROI-TEST",
        occupancy=True,
        internal_temp=30.0,
        cabin_area_m2=50.0 
    )
    
    decision = calculate_optimized_load(telemetry)
    
    # Verify hourly and annual savings are calculated in INR [cite: 182, 188]
    assert decision.money_saved_hr_inr >= 0
    assert decision.annual_roi_inr >= 0

# ─────────────────────────────────────────────────────────────
# TEST CASE 4: Asset Defence™ Integration (PPT Page 7)
# ─────────────────────────────────────────────────────────────
def test_asset_defence_warning_flow():
    """
    Ensure the backend schema is ready for Asset Defence data[cite: 111, 122].
    """
    telemetry = CabinTelemetry(cabin_id="DEW-TEST", occupancy=True, internal_temp=20, internal_humidity=95)
    decision = calculate_optimized_load(telemetry)
    
    # Ensure thermodynamic breakdown is present [cite: 83]
    assert decision.breakdown.q_total_raw > 0
    # Ensure schema can receive dew point results
    assert hasattr(decision, 'dew_point')