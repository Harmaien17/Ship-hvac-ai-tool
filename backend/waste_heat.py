"""
MAR-HVAC AI — Waste Heat Recovery Calculator
backend/waste_heat.py

WEEK 5

Formula:
  Q_gross = m_dot * Cp_exhaust * (T_exhaust - T_ambient)
  Q_recoverable = Q_gross * recovery_efficiency   (typically 0.35 for marine HRSGs)
  Q_hvac_offset = Q_recoverable (can be used to reduce HVAC compressor demand)

  CO2 saved = (Q_recoverable / 3600) * emission_factor_kg_per_kWh

Physical background:
  Marine diesel engines reject ~30-40% of fuel energy as exhaust heat.
  A Heat Recovery Steam Generator (HRSG) can capture ~35% of that exhaust energy.
  The captured energy can power absorption chillers or pre-heat cabin air,
  directly reducing the electrical load on HVAC compressors.

Reference: IMO MEPC.203(62), ASHRAE HVAC Applications Chapter 48 (Marine)

YOU are the only one who edits this file.
"""

import logging
from schemas import WasteHeatInput, WasteHeatResult

logger = logging.getLogger("mar_hvac.waste_heat")

# Specific heat of diesel exhaust gas (approximated as air + combustion products)
CP_EXHAUST_KJ_PER_KG_K = 1.09   # kJ / (kg·K)  — slightly higher than pure air (1.005)

# CO2 emission factor for marine heavy fuel oil (HFO)
# Burning 1 kWh of HFO produces ~0.28 kg CO2 (based on IMO GHG study 2020)
CO2_KG_PER_KWH_HFO = 0.28


def calculate_waste_heat_recovery(inp: WasteHeatInput) -> WasteHeatResult:
    """
    Calculate waste heat recovery potential from engine exhaust.

    Steps:
      1. Q_gross = m_dot * Cp * (T_exhaust - T_ambient)
      2. Q_recoverable = Q_gross * efficiency
      3. HVAC offset = Q_recoverable (1:1 offset, conservative)
      4. CO2 saved = Q_recoverable * emission_factor

    Returns WasteHeatResult with all values and a log.
    """
    log: list[str] = []

    log.append("=== WASTE HEAT RECOVERY ANALYSIS ===")
    log.append(f"  Exhaust temp   : {inp.exhaust_temp_c:.0f}C")
    log.append(f"  Ambient temp   : {inp.ambient_temp_c:.0f}C")
    log.append(f"  Exhaust flow   : {inp.exhaust_flow_kg_s:.2f} kg/s")
    log.append(f"  HRSG efficiency: {inp.recovery_efficiency:.0%}")
    log.append("")

    # Step 1: Gross heat in exhaust stream
    delta_t_exhaust  = inp.exhaust_temp_c - inp.ambient_temp_c
    q_gross_kw       = inp.exhaust_flow_kg_s * CP_EXHAUST_KJ_PER_KG_K * delta_t_exhaust
    # kJ/s = kW (because m_dot [kg/s] * Cp [kJ/kg·K] * dT [K] = kJ/s = kW)

    # Step 2: Recoverable heat after HRSG efficiency loss
    q_recoverable_kw = q_gross_kw * inp.recovery_efficiency

    # Step 3: HVAC compressor demand offset
    # Assumption: recovered heat drives absorption chiller with COP_absorption = 0.7
    # So electrical HVAC savings = Q_recoverable * 0.7
    # For simplicity and conservative pitch: use direct 1:1 offset
    hvac_offset_kw   = q_recoverable_kw

    # Step 4: CO2 savings
    # Q_recoverable_kw -> kWh in 1 hour -> * emission_factor
    co2_saved_per_hr = q_recoverable_kw * CO2_KG_PER_KWH_HFO

    log.append("--- CALCULATION ---")
    log.append(f"  Q_gross        : {inp.exhaust_flow_kg_s:.2f} kg/s x {CP_EXHAUST_KJ_PER_KG_K} kJ/kgK x {delta_t_exhaust:.0f}K")
    log.append(f"                 = {q_gross_kw:.1f} kW of heat in exhaust stream")
    log.append(f"  Q_recoverable  : {q_gross_kw:.1f} x {inp.recovery_efficiency:.0%} = {q_recoverable_kw:.1f} kW")
    log.append(f"  HVAC offset    : {hvac_offset_kw:.1f} kW reduction in compressor demand")
    log.append(f"  CO2 saved      : {co2_saved_per_hr:.2f} kg/hr ({co2_saved_per_hr * 24:.1f} kg/day)")
    log.append("")
    log.append(f"=== RESULT: {q_recoverable_kw:.1f} kW recoverable | {hvac_offset_kw:.1f} kW HVAC offset ===")

    logger.info(
        f"[WASTE_HEAT] Gross={q_gross_kw:.1f}kW | "
        f"Recoverable={q_recoverable_kw:.1f}kW | "
        f"HVAC_offset={hvac_offset_kw:.1f}kW"
    )

    return WasteHeatResult(
        gross_heat_kw       = round(q_gross_kw, 2),
        recoverable_kw      = round(q_recoverable_kw, 2),
        hvac_offset_kw      = round(hvac_offset_kw, 2),
        co2_saved_kg_per_hr = round(co2_saved_per_hr, 3),
        log_lines           = log,
    )


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s: %(message)s")

    print("\n=== waste_heat.py Test ===\n")

    test_input = WasteHeatInput(
        exhaust_temp_c    = 380.0,
        ambient_temp_c    = 32.0,
        exhaust_flow_kg_s = 2.5,
        recovery_efficiency = 0.35,
    )
    result = calculate_waste_heat_recovery(test_input)
    for line in result.log_lines:
        print(line)
    print(f"\nGross: {result.gross_heat_kw} kW")
    print(f"Recoverable: {result.recoverable_kw} kW")
    print(f"HVAC offset: {result.hvac_offset_kw} kW")
    print(f"CO2 saved: {result.co2_saved_kg_per_hr} kg/hr")