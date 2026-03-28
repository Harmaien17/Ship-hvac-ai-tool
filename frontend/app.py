"""
MAR-HVAC AI — Command Center Dashboard
frontend/app.py

FINAL MERGED VERSION — Week 3 + Week 4 + New Requirements (1–7)

New in this version:
  - Req 1: Occupant Count (number_input)
  - Req 2: Window Area slider → q_fenestration bar
  - Req 3: Equipment Wattage → q_equipment bar
  - Req 4: Sun-Exposed Ceiling Area → q_ceiling bar
  - Req 5: Floor above Heat Source → q_floor_conduction bar
  - Req 6: Cabin Area expanded to 2000 m²
  - Req 7: Ship Length slider
  - 11-bar heat load breakdown chart (was 6)
  - All Week 3 + Week 4 features preserved

Run with:
  cd frontend
  streamlit run app.py
"""

import os
import sys
import time
import datetime
from typing import Optional

import streamlit as st
import requests
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.0.216:8000")
API_TIMEOUT = 10

st.set_page_config(
    page_title="MAR-HVAC AI",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────
# CSS — INDUSTRIAL MARITIME DARK THEME
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;600;700;900&display=swap');

  :root {
    --navy:    #04080f;
    --panel:   #0d1726;
    --surface: #111f35;
    --border:  #1e3a5f;
    --cyan:    #00d4ff;
    --teal:    #06b6d4;
    --green:   #10b981;
    --amber:   #f59e0b;
    --red:     #ef4444;
    --blue:    #3b82f6;
    --purple:  #7c3aed;
    --white:   #e2e8f0;
    --muted:   #64748b;
    --mono:    'Share Tech Mono', monospace;
    --ui:      'Exo 2', sans-serif;
  }

  html, body, [data-testid="stAppViewContainer"] {
    background: var(--navy) !important;
    color: var(--white) !important;
    font-family: var(--ui) !important;
  }
  [data-testid="stSidebar"] {
    background: var(--panel) !important;
    border-right: 1px solid var(--border) !important;
  }
  [data-testid="stHeader"] { background: transparent !important; }

  h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: var(--ui) !important;
    color: var(--white) !important;
    font-weight: 700 !important;
  }
  label, p, .stMarkdown p, .stSlider label {
    font-family: var(--ui) !important;
    color: var(--white) !important;
  }

  /* Sliders */
  .stSlider [data-baseweb="slider"] [role="slider"] {
    background: var(--cyan) !important;
    border-color: var(--cyan) !important;
  }

  /* Buttons */
  .stButton > button {
    background: var(--surface) !important;
    color: var(--cyan) !important;
    border: 1px solid var(--border) !important;
    border-radius: 4px !important;
    font-family: var(--mono) !important;
    font-size: 0.8rem !important;
    letter-spacing: 0.08em !important;
  }
  .stButton > button:hover {
    border-color: var(--cyan) !important;
    box-shadow: 0 0 10px rgba(0,212,255,0.3) !important;
  }

  /* Metrics */
  [data-testid="stMetric"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 10px 14px !important;
  }
  [data-testid="stMetricLabel"] {
    color: var(--muted) !important;
    font-family: var(--mono) !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
  }
  [data-testid="stMetricValue"] {
    color: var(--cyan) !important;
    font-family: var(--mono) !important;
    font-size: 1.6rem !important;
  }

  /* Selectbox */
  .stSelectbox > div > div {
    background: var(--surface) !important;
    border-color: var(--border) !important;
    color: var(--white) !important;
  }

  /* Toggle */
  .stCheckbox label, .stToggle label { color: var(--white) !important; }

  hr { border-color: var(--border) !important; }

  /* Decision log */
  .decision-log {
    background: #020b14;
    border: 1px solid #1e3a5f;
    border-left: 3px solid #7c3aed;
    border-radius: 6px;
    padding: 14px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.75rem;
    line-height: 1.7;
    color: #a8d8ea;
    max-height: 380px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .decision-log .log-header  { color: #00d4ff; }
  .decision-log .log-warn    { color: #f59e0b; }
  .decision-log .log-error   { color: #ef4444; }
  .decision-log .log-ok      { color: #10b981; }
  .decision-log .log-section { color: #7dd3fc; }

  /* Alert banners */
  .alert-red {
    background: rgba(239,68,68,0.12);
    border: 1px solid rgba(239,68,68,0.5);
    border-left: 4px solid #ef4444;
    border-radius: 5px;
    padding: 12px 16px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.82rem;
    color: #ef4444;
    margin: 6px 0;
  }
  .alert-amber {
    background: rgba(245,158,11,0.12);
    border: 1px solid rgba(245,158,11,0.5);
    border-left: 4px solid #f59e0b;
    border-radius: 5px;
    padding: 12px 16px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.82rem;
    color: #f59e0b;
    margin: 6px 0;
  }
  .alert-blue {
    background: rgba(59,130,246,0.12);
    border: 1px solid rgba(59,130,246,0.5);
    border-left: 4px solid #3b82f6;
    border-radius: 5px;
    padding: 12px 16px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.82rem;
    color: #3b82f6;
    margin: 6px 0;
  }

  /* Load display */
  .load-box {
    background: linear-gradient(135deg, #0d1726, #111f35);
    border: 1px solid #1e3a5f;
    border-top: 3px solid #00d4ff;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
  }
  .load-box.heating-mode { border-top-color: #3b82f6 !important; }
  .load-number {
    font-family: 'Share Tech Mono', monospace;
    font-size: 4rem;
    font-weight: 700;
    color: #00d4ff;
    text-shadow: 0 0 28px rgba(0,212,255,0.5);
    line-height: 1;
  }
  .load-number.heating { color: #3b82f6; text-shadow: 0 0 28px rgba(59,130,246,0.5); }
  .load-unit {
    font-family: 'Share Tech Mono', monospace;
    font-size: 1.1rem;
    color: #64748b;
    margin-top: 4px;
  }

  /* Mode badge */
  .mode-badge {
    display: inline-block;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.14em;
    padding: 4px 12px;
    border-radius: 3px;
    margin-top: 10px;
    border: 1px solid;
  }
  .mode-FULL_COOLING        { color:#ef4444; border-color:#ef4444; background:rgba(239,68,68,0.1); }
  .mode-REDUCED_COOLING     { color:#06b6d4; border-color:#06b6d4; background:rgba(6,182,212,0.1); }
  .mode-MAINTENANCE_COOLING { color:#f59e0b; border-color:#f59e0b; background:rgba(245,158,11,0.1); }
  .mode-STANDBY             { color:#10b981; border-color:#10b981; background:rgba(16,185,129,0.1); }
  .mode-FAILSAFE            { color:#ef4444; border-color:#ef4444; background:rgba(239,68,68,0.1); }
  .mode-EMERGENCY_HEAT      { color:#3b82f6; border-color:#3b82f6; background:rgba(59,130,246,0.1); }
  .mode-CORROSION_PREVENTION{ color:#ef4444; border-color:#ef4444; background:rgba(239,68,68,0.1); }
  .mode-MOLD_ALERT          { color:#f59e0b; border-color:#f59e0b; background:rgba(245,158,11,0.1); }

  /* Savings box */
  .savings-box {
    background: #111f35;
    border: 1px solid #1e3a5f;
    border-top: 3px solid #10b981;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
  }
  .savings-number {
    font-family: 'Share Tech Mono', monospace;
    font-size: 2.8rem;
    font-weight: 700;
    color: #10b981;
    text-shadow: 0 0 20px rgba(16,185,129,0.4);
  }

  /* Status rows */
  .status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 5px 10px;
    background: #111f35;
    border: 1px solid #1e3a5f;
    border-radius: 3px;
    margin: 2px 0;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem;
  }
  .label-muted { color: #64748b; }

  /* Section labels */
  .section-label {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.6rem;
    color: #64748b;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    border-bottom: 1px solid #1e3a5f;
    padding-bottom: 3px;
    margin-bottom: 10px;
  }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def api_optimize(payload: dict) -> Optional[dict]:
    """Call backend /optimize. Returns result dict or None."""
    try:
        r = requests.post(
            f"{BACKEND_URL}/api/v1/optimize",
            json=payload,
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        st.session_state["api_error"] = str(e)
        return None


def api_health() -> Optional[dict]:
    try:
        r = requests.get(f"{BACKEND_URL}/api/v1/health", timeout=3)
        return r.json()
    except Exception:
        return None


def api_forecast() -> list[dict]:
    try:
        r = requests.get(f"{BACKEND_URL}/api/v1/weather/forecast/chart", timeout=6)
        return r.json().get("points", [])
    except Exception:
        return []


def run_local_engine(payload: dict) -> dict:
    """
    Fallback: run the engine locally if backend is down.
    Lets you demo the dashboard without running uvicorn.
    """
    try:
        backend_path = os.path.join(os.path.dirname(__file__), "..", "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from schemas import CabinTelemetry as CT, CabinSide as CS
        from hvac_engine import calculate_optimized_load
        tel = CT(**payload)
        return calculate_optimized_load(tel).model_dump()
    except Exception as e:
        return {"error": str(e)}


def colorise_log(lines: list[str]) -> str:
    """Wrap log lines in coloured spans for the terminal display."""
    out = []
    for line in lines:
        escaped = line.replace("<", "&lt;").replace(">", "&gt;")
        if "===" in line or "FINAL" in line:
            out.append(f'<span class="log-header">{escaped}</span>')
        elif any(x in line for x in ["!", "ALERT", "RISK", "FAILSAFE", "STALE", "CRITICAL", "CORROSION", "MOLD"]):
            out.append(f'<span class="log-warn">{escaped}</span>')
        elif any(x in line for x in ["OK:", "saved", "Saved"]):
            out.append(f'<span class="log-ok">{escaped}</span>')
        elif "---" in line:
            out.append(f'<span class="log-section">{escaped}</span>')
        else:
            out.append(escaped)
    return "\n".join(out)


def mode_color(mode: str) -> str:
    return {
        "FULL_COOLING":         "#ef4444",
        "REDUCED_COOLING":      "#06b6d4",
        "MAINTENANCE_COOLING":  "#f59e0b",
        "STANDBY":              "#10b981",
        "FAILSAFE":             "#ef4444",
        "EMERGENCY_HEAT":       "#3b82f6",
        "CORROSION_PREVENTION": "#ef4444",
        "MOLD_ALERT":           "#f59e0b",
    }.get(mode, "#64748b")


# ─────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────

for key, default in [
    ("result", None),
    ("api_error", None),
    ("backend_mode", "unknown"),
    ("forecast_points", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding:8px 0 14px;">
      <div style="font-family:'Share Tech Mono',monospace; font-size:1.05rem; color:#00d4ff;">
        MAR-HVAC AI
      </div>
      <div style="font-family:'Share Tech Mono',monospace; font-size:0.58rem;
                  color:#64748b; letter-spacing:0.2em; margin-top:2px;">
        COMMAND CENTER v2.0
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Cabin Geometry ─────────────────────────────────────
    st.markdown("##### 🛏️ Cabin Geometry")
    cabin_id    = st.text_input("Cabin ID", value="CABIN-A3")

    # REQ 6: Area expanded to 2000 m²
    cabin_area  = st.slider("Floor Area (m²)", 0.0, 2000.0, 25.0, 5.0)

    # REQ 7: Ship Length
    ship_length = st.slider("Ship Length (m)", 0, 500, 120)

    # REQ 2: Window Area
    window_area = st.slider("Window Area (m²)", 0.0, 50.0, 1.5, 0.5)

    target_temp = st.slider("Target Setpoint (°C)", 18.0, 28.0, 22.0, 0.5)
    cabin_side  = st.selectbox("Vessel Side", ["interior","starboard","port","bow","stern"], index=0)
    market      = st.selectbox("Vessel Type", ["cargo","cruise","navy","hospital","yacht"], index=0)

    st.markdown("---")

    # ── Sensors ────────────────────────────────────────────
    st.markdown("##### 📡 Sensors (DHT22 + PIR)")
    occupancy     = st.toggle("🧍 Occupied (PIR)", value=False)

    # REQ 1: Occupant Count
    occ_count     = st.number_input("Occupant Count", min_value=0, max_value=100,
                                     value=2 if occupancy else 0)

    internal_temp = st.slider("Internal Temp °C", 15.0, 42.0, 26.0, 0.5)
    internal_rh   = st.slider("Humidity % (DHT22)", 30.0, 98.0, 68.0, 1.0)

    st.markdown("---")

    # ── Load Factors (new) ─────────────────────────────────
    st.markdown("##### ⚙️ Load Factors")

    # REQ 3: Equipment Wattage
    equip_watts = st.number_input("Equipment Watts (Laptops/Stove/etc.)",
                                   min_value=0, max_value=10000, value=450)

    # REQ 4: Ceiling exposed to sun
    ceil_area   = st.slider("Sun-Exposed Ceiling (m²)", 0.0, float(max(cabin_area, 10.0)), 10.0)

    # REQ 5: Floor above heat source
    floor_area  = st.slider("Floor above Heat Source (m²)", 0.0, float(max(cabin_area, 10.0)), 5.0)

    st.markdown("---")

    # ── External Conditions ─────────────────────────────────
    st.markdown("##### 🌍 External Conditions")
    manual_weather = st.toggle("Manual Weather Override", value=True)
    if manual_weather:
        external_temp    = st.slider("External Temp °C", -5.0, 50.0, 34.0, 0.5)
        solar_irradiance = st.slider("Solar Irradiance (W/m²)", 0.0, 1200.0, 650.0, 25.0)
    else:
        external_temp    = None
        solar_irradiance = None
        st.caption("Using live API → cache → forecast → DHT22")

    st.markdown("---")

    # ── Ship Dynamics ───────────────────────────────────────
    st.markdown("##### ⚙️ Ship Dynamics")
    direct_sunlight  = st.toggle("☀️ Direct Sunlight",  value=False)
    heat_soaked_hull = st.toggle("🔥 Heat-Soaked Hull", value=False)
    engine_adjacent  = st.toggle("⚙️ Engine Adjacent",  value=False)

    st.markdown("---")

    # ── Controls ────────────────────────────────────────────
    col_run, col_ref = st.columns(2)
    with col_run:
        run_btn = st.button("⚡ CALCULATE", use_container_width=True)
    with col_ref:
        fc_btn = st.button("🔄 FORECAST", use_container_width=True,
                           help="Fetch 7-day forecast buffer")

    st.caption(f"Backend: `{BACKEND_URL}`")


# ─────────────────────────────────────────────────────────────
# BUILD PAYLOAD
# ─────────────────────────────────────────────────────────────

payload = {
    # Core identity
    "cabin_id":                  cabin_id,
    "market_segment":            market,
    "cabin_side":                cabin_side,
    "target_temp":               target_temp,

    # Geometry (Req 6 + 7 + 2)
    "cabin_area_m2":             cabin_area,
    "ship_length_m":             ship_length,
    "window_area_m2":            window_area,

    # Sensors (Req 1)
    "occupancy":                 occupancy,
    "occupant_count":            occ_count,
    "internal_temp":             internal_temp,
    "internal_humidity":         internal_rh,

    # External
    "external_temp":             external_temp if manual_weather else None,
    "solar_irradiance":          solar_irradiance if manual_weather else None,

    # Ship dynamics
    "direct_sunlight":           direct_sunlight,
    "heat_soaked_hull":          heat_soaked_hull,
    "engine_adjacent":           engine_adjacent,

    # Load factors (Req 3 + 4 + 5)
    "equipment_wattage":         equip_watts,
    "ceiling_area_exposed_m2":   ceil_area,
    "floor_area_exposed_m2":     floor_area,
}


# ─────────────────────────────────────────────────────────────
# RUN CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate():
    result = api_optimize(payload)
    if result and "mode" in result:
        st.session_state["backend_mode"] = "api"
        st.session_state["result"]       = result
        st.session_state["api_error"]    = None
    else:
        result = run_local_engine(payload)
        if "mode" in result:
            st.session_state["backend_mode"] = "local"
            st.session_state["result"]       = result
        else:
            st.session_state["backend_mode"] = "offline"


if run_btn or st.session_state["result"] is None:
    with st.spinner("Analyzing Thermal Dynamics..."):
        calculate()

if fc_btn:
    try:
        r = requests.get(f"{BACKEND_URL}/api/v1/weather/forecast", timeout=10)
        d = r.json()
        if d.get("success"):
            st.sidebar.success(f"Forecast saved — {d.get('points_saved', 0)} points")
        else:
            st.sidebar.error(d.get("message", "Fetch failed"))
    except Exception:
        st.sidebar.error("Backend not reachable")


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

health   = api_health()
bm       = st.session_state["backend_mode"]
bm_color = {"api": "#10b981", "local": "#f59e0b", "offline": "#ef4444"}.get(bm, "#64748b")
bm_label = {"api": "● BACKEND LIVE", "local": "◈ LOCAL ENGINE", "offline": "○ OFFLINE"}.get(bm, "?")

weather_label = "○ NO WEATHER"
weather_color = "#64748b"
if health:
    wc = health.get("weather_cache", {})
    fb = health.get("forecast_buffer", {})
    if wc.get("status") == "cache":
        weather_label = f"● LIVE {wc.get('temp_c','?')}°C"
        weather_color = "#10b981"
    elif fb.get("available"):
        weather_label = f"◈ FORECAST {fb.get('age_hours','?'):.0f}h OLD"
        weather_color = "#f59e0b"
    else:
        weather_label = "○ FAILSAFE"
        weather_color = "#ef4444"

st.markdown(f"""
<div style="background:linear-gradient(90deg,#0d1726,#111f35); border:1px solid #1e3a5f;
            border-bottom:2px solid #00d4ff; padding:14px 20px; border-radius:6px;
            margin-bottom:16px; display:flex; justify-content:space-between; align-items:center;">
  <div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:1.2rem; color:#00d4ff;
                letter-spacing:0.1em;">🚢 MAR-HVAC AI — COMMAND CENTER</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#64748b;
                letter-spacing:0.16em; margin-top:2px;">
      INTELLIGENT HEAT LOAD OPTIMISATION FOR MARINE VESSELS
    </div>
  </div>
  <div style="display:flex; gap:8px;">
    <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem;
                 color:{bm_color}; border:1px solid {bm_color}; padding:3px 10px;
                 border-radius:20px; background:rgba(0,0,0,0.3);">{bm_label}</span>
    <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem;
                 color:{weather_color}; border:1px solid {weather_color}; padding:3px 10px;
                 border-radius:20px; background:rgba(0,0,0,0.3);">{weather_label}</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# MAIN CONTENT
# ─────────────────────────────────────────────────────────────

result  = st.session_state.get("result")
api_err = st.session_state.get("api_error")

if api_err:
    st.markdown(f'<div class="alert-red">⚠ API Error: {api_err} — Running local engine fallback.</div>',
                unsafe_allow_html=True)

if result and "mode" in result:
    mode     = result.get("mode", "UNKNOWN")
    load_kw  = result.get("optimized_load_kw", 0.0)
    savings  = result.get("energy_saved_percent", 0.0)
    setpoint = result.get("setpoint_actual", target_temp)
    wx_src   = result.get("weather_source", "unknown")
    dew_pt   = result.get("dew_point", None)
    warns    = result.get("warnings", [])
    is_heat  = mode == "EMERGENCY_HEAT"

    # ── Alert banners ────────────────────────────────────────
    for w in warns:
        if "CORROSION" in w:
            st.markdown(f'<div class="alert-red">🚨 {w}</div>', unsafe_allow_html=True)
        elif "MOLD" in w:
            st.markdown(f'<div class="alert-amber">⚠ {w}</div>', unsafe_allow_html=True)
        elif "HOSPITAL" in w or "MEDICINE" in w:
            st.markdown(f'<div class="alert-red">🏥 {w}</div>', unsafe_allow_html=True)
        elif "FAILSAFE" in w or "STALE" in w:
            st.markdown(f'<div class="alert-amber">📡 {w}</div>', unsafe_allow_html=True)

    if is_heat:
        st.markdown(
            '<div class="alert-blue">🌨️ HEATING MODE ACTIVE — External temp below setpoint. '
            'Arctic/cold route detected. System switched to heating load.</div>',
            unsafe_allow_html=True
        )

    # ── Row 1: Load + Savings + Ship Status ─────────────────
    col_load, col_sav, col_status = st.columns([2, 1, 1])

    with col_load:
        num_class    = "load-number heating" if is_heat else "load-number"
        box_class    = "load-box heating-mode" if is_heat else "load-box"
        mode_display = mode.replace("_", " ")
        st.markdown(f"""
        <div class="{box_class}">
          <div class="section-label">// OPTIMISED HVAC LOAD</div>
          <div class="{num_class}">{load_kw:.3f}</div>
          <div class="load-unit">kilowatts</div>
          <div>
            <span class="mode-badge mode-{mode}">{mode_display}</span>
          </div>
          <div style="margin-top:10px; font-family:'Share Tech Mono',monospace;
                      font-size:0.68rem; color:#64748b; letter-spacing:0.09em;">
            SETPOINT: {setpoint:.1f}°C &nbsp;|&nbsp; {cabin_id} &nbsp;|&nbsp;
            SRC: {wx_src.upper()} &nbsp;|&nbsp; SEG: {market.upper()} &nbsp;|&nbsp;
            SHIP: {ship_length}m
          </div>
        </div>
        """, unsafe_allow_html=True)

    with col_sav:
        ghost_active = mode == "MAINTENANCE_COOLING"
        sav_border   = "#f59e0b" if ghost_active else ("#3b82f6" if is_heat else "#10b981")
        sav_color    = "#f59e0b" if ghost_active else ("#3b82f6" if is_heat else "#10b981")
        sav_icon     = "👻" if ghost_active else ("🌨️" if is_heat else "⚡")
        sav_label    = "GHOST PROTOCOL" if ghost_active else ("HEATING MODE" if is_heat else "ENERGY SAVED")

        st.markdown(f"""
        <div class="savings-box" style="border-top-color:{sav_border};">
          <div class="section-label">// {sav_label}</div>
          <div class="savings-number" style="color:{sav_color};
               text-shadow:0 0 20px {sav_color}55;">
            {sav_icon} {savings:.1f}%
          </div>
          <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem;
                      color:#64748b; margin-top:6px;">
            vs full-load baseline
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # Mode-specific status box
        if mode == "MAINTENANCE_COOLING":
            st.markdown(f"""
            <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3);
                        border-left:3px solid #f59e0b; border-radius:5px; padding:10px;">
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:#f59e0b;">
                👻 GHOST COOLING ACTIVE
              </div>
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.72rem; color:#e2e8f0; margin-top:4px;">
                Empty cabin. Running {100-savings:.0f}% load.<br>Setpoint: {setpoint:.1f}°C
              </div>
            </div>""", unsafe_allow_html=True)
        elif mode == "CORROSION_PREVENTION":
            st.markdown("""
            <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.4);
                        border-left:3px solid #ef4444; border-radius:5px; padding:10px;">
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:#ef4444;">
                🚨 CORROSION PREVENTION
              </div>
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.72rem; color:#e2e8f0; margin-top:4px;">
                Fans at 30%. Preventing hull<br>condensation. Asset protection.
              </div>
            </div>""", unsafe_allow_html=True)
        elif mode == "MOLD_ALERT":
            st.markdown("""
            <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.4);
                        border-left:3px solid #f59e0b; border-radius:5px; padding:10px;">
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:#f59e0b;">
                ⚠ MOLD ALERT
              </div>
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.72rem; color:#e2e8f0; margin-top:4px;">
                Dehumidification active.<br>Ventilation increased.
              </div>
            </div>""", unsafe_allow_html=True)
        else:
            occ_color = "#10b981" if occupancy else "#f59e0b"
            occ_label = "OCCUPIED — FULL COMFORT" if occupancy else "EMPTY — MONITORING"
            st.markdown(f"""
            <div style="background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2);
                        border-left:3px solid {occ_color}; border-radius:5px; padding:10px;">
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:{occ_color};">
                {'✓' if occupancy else '○'} {occ_label}
              </div>
              <div style="font-family:'Share Tech Mono',monospace; font-size:0.72rem; color:#e2e8f0; margin-top:4px;">
                Occupants: {occ_count} &nbsp;|&nbsp; Setpoint: {setpoint:.1f}°C
              </div>
            </div>""", unsafe_allow_html=True)

    with col_status:
        st.markdown('<div class="section-label">// SHIP DYNAMICS</div>', unsafe_allow_html=True)

        dynamics = [
            ("☀️ Direct Sun",   direct_sunlight,  "ACTIVE",   "NONE",   "#ef4444"),
            ("🔥 Hull Soaked",  heat_soaked_hull, "ACTIVE",   "NORMAL", "#ef4444"),
            ("⚙️ Engine Adj",  engine_adjacent,  "ACTIVE",   "CLEAR",  "#f97316"),
            ("🧍 Occupancy",    occupancy,         "OCCUPIED", "EMPTY",  "#10b981"),
        ]
        for label, active, on_txt, off_txt, act_color in dynamics:
            txt   = on_txt if active else off_txt
            color = act_color if active else ("#f59e0b" if "Occupancy" in label and not active else "#64748b")
            st.markdown(f"""
            <div class="status-row">
              <span class="label-muted">{label}</span>
              <span style="color:{color}; font-weight:700; font-size:0.75rem;">{txt}</span>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # Dew point display
        if dew_pt is not None:
            margin   = internal_temp - dew_pt
            dp_color = "#ef4444" if margin < 1.0 else ("#f59e0b" if margin < 3.0 else "#10b981")
            st.markdown(f"""
            <div class="status-row">
              <span class="label-muted">💧 Dew Point</span>
              <span style="color:{dp_color}; font-weight:700;">{dew_pt:.1f}°C</span>
            </div>
            <div class="status-row">
              <span class="label-muted">📏 Margin</span>
              <span style="color:{dp_color}; font-weight:700;">{margin:.1f}°C</span>
            </div>""", unsafe_allow_html=True)

        ext_disp = f"{external_temp:.1f}°C" if manual_weather and external_temp else "AUTO"
        st.markdown(f"""
        <div class="status-row">
          <span class="label-muted">🌡️ Ext Temp</span>
          <span style="color:#00d4ff;">{ext_disp}</span>
        </div>
        <div class="status-row">
          <span class="label-muted">💧 Humidity</span>
          <span style="color:#00d4ff;">{internal_rh:.0f}%</span>
        </div>
        <div class="status-row">
          <span class="label-muted">🏢 Segment</span>
          <span style="color:#00d4ff;">{market.upper()}</span>
        </div>
        <div class="status-row">
          <span class="label-muted">🚢 Ship Len</span>
          <span style="color:#00d4ff;">{ship_length}m</span>
        </div>
        <div class="status-row">
          <span class="label-muted">🪟 Window</span>
          <span style="color:#00d4ff;">{window_area:.1f}m²</span>
        </div>
        <div class="status-row">
          <span class="label-muted">🔌 Equip</span>
          <span style="color:#00d4ff;">{equip_watts}W</span>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── Row 2: AI Decision Log + 11-Bar Breakdown Chart ─────
    col_log, col_chart = st.columns([3, 2])

    with col_log:
        st.markdown('<div class="section-label">// AI DECISION LOG — REASONING TRACE</div>',
                    unsafe_allow_html=True)
        log_lines = result.get("decision_log", ["No log available."])
        ts        = time.strftime("%H:%M:%S")
        log_html  = colorise_log(log_lines)
        st.markdown(f"""
        <div class="decision-log">
          <span class="log-header">MAR-HVAC AI ENGINE — {ts} — {cabin_id}</span>

          {log_html}
        </div>""", unsafe_allow_html=True)

    with col_chart:
        st.markdown('<div class="section-label">// COMPLETE HEAT LOAD BREAKDOWN — 11 LINE ITEMS (kW)</div>',
                    unsafe_allow_html=True)
        bd = result.get("breakdown", {})

        # ── 11-bar chart (upgraded from 6) ──────────────────
        labels = [
            "Wall Transmission",
            "Solar (Porthole)",
            "Fenestration (Windows)",   # REQ 2
            "Metabolic (People)",       # REQ 1
            "Equipment",                # REQ 3
            "Engine Radiant",
            "Thermal Lag",
            "Ceiling (Solar-Air)",      # REQ 4
            "Floor Conduction",         # REQ 5
            "Latent (Salt Air)",
            "Heating Load",
        ]
        values = [
            bd.get("q_transmission",        0),
            bd.get("q_solar",               0),
            bd.get("q_fenestration",        0),
            bd.get("q_metabolic",           0),
            bd.get("q_equipment",           0),
            bd.get("q_engine_radiant",      0),
            bd.get("q_thermal_lag",         0),
            bd.get("q_ceiling",             0),
            bd.get("q_floor_conduction",    0),
            bd.get("q_latent",              0),
            bd.get("heating_load_kw",       0),
        ]
        bar_colors = [
            "#06b6d4",  # Wall Transmission
            "#f59e0b",  # Solar
            "#7dd3fc",  # Fenestration
            "#10b981",  # Metabolic
            "#a78bfa",  # Equipment
            "#ef4444",  # Engine Radiant
            "#f97316",  # Thermal Lag
            "#fbbf24",  # Ceiling
            "#84cc16",  # Floor
            "#7c3aed",  # Latent
            "#3b82f6",  # Heating Load
        ]

        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation="h",
            marker=dict(color=bar_colors, line=dict(color="#1e3a5f", width=1)),
            text=[f"{v:.3f}" for v in values],
            textposition="outside",
            textfont=dict(family="Share Tech Mono", size=9, color="#e2e8f0"),
        ))
        fig.add_vline(
            x=load_kw, line_dash="dash", line_color="#00d4ff", line_width=1.5,
            annotation_text=f"Optimised: {load_kw:.3f}kW",
            annotation_font=dict(color="#00d4ff", size=9, family="Share Tech Mono"),
            annotation_position="top right",
        )
        fig.update_layout(
            paper_bgcolor="#04080f", plot_bgcolor="#0d1726",
            font=dict(family="Share Tech Mono", size=9, color="#94a3b8"),
            margin=dict(l=10, r=70, t=10, b=20), height=370,
            xaxis=dict(gridcolor="#1e3a5f", zeroline=True, zerolinecolor="#1e3a5f"),
            yaxis=dict(gridcolor="#1e3a5f"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Row 3: Asset Defence Gauges + 7-Day Forecast ────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    col_gauge, col_fc = st.columns([1, 2])

    with col_gauge:
        st.markdown('<div class="section-label">// ASSET DEFENCE GAUGES</div>',
                    unsafe_allow_html=True)

        # Dew point gauge
        if dew_pt is not None:
            fig_dew = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=internal_temp,
                delta={"reference": dew_pt, "increasing": {"color": "#10b981"},
                       "decreasing": {"color": "#ef4444"}},
                title={"text": "Temp vs Dew Point (°C)",
                       "font": {"family": "Share Tech Mono", "size": 11, "color": "#94a3b8"}},
                number={"font": {"family": "Share Tech Mono", "size": 28, "color": "#00d4ff"},
                        "suffix": "°C"},
                gauge={
                    "axis": {"range": [dew_pt - 5, internal_temp + 10], "tickcolor": "#64748b"},
                    "bar":  {"color": "#00d4ff"},
                    "steps": [
                        {"range": [dew_pt - 5, dew_pt + 1],       "color": "rgba(239,68,68,0.3)"},
                        {"range": [dew_pt + 1, dew_pt + 3],       "color": "rgba(245,158,11,0.25)"},
                        {"range": [dew_pt + 3, internal_temp + 10],"color": "rgba(16,185,129,0.15)"},
                    ],
                    "threshold": {
                        "line": {"color": "#ef4444", "width": 2},
                        "thickness": 0.8,
                        "value": dew_pt + 1,
                    },
                },
            ))
            fig_dew.update_layout(
                paper_bgcolor="#04080f", font_color="#94a3b8",
                margin=dict(l=20, r=20, t=40, b=10), height=200,
            )
            st.plotly_chart(fig_dew, use_container_width=True, config={"displayModeBar": False})

        # Humidity gauge
        mold_thresh = {"cargo":70,"cruise":65,"navy":60,"hospital":55,"yacht":60}.get(market, 70)
        fig_rh = go.Figure(go.Indicator(
            mode="gauge+number",
            value=internal_rh,
            title={"text": f"Humidity % (mold threshold: {mold_thresh}%)",
                   "font": {"family": "Share Tech Mono", "size": 10, "color": "#94a3b8"}},
            number={"font": {"family": "Share Tech Mono", "size": 28, "color": "#06b6d4"},
                    "suffix": "%"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar":  {"color": "#06b6d4"},
                "steps": [
                    {"range": [0, mold_thresh],   "color": "rgba(16,185,129,0.15)"},
                    {"range": [mold_thresh, 100],  "color": "rgba(245,158,11,0.2)"},
                ],
                "threshold": {
                    "line": {"color": "#f59e0b", "width": 2},
                    "thickness": 0.8,
                    "value": mold_thresh,
                },
            },
        ))
        fig_rh.update_layout(
            paper_bgcolor="#04080f", font_color="#94a3b8",
            margin=dict(l=20, r=20, t=40, b=10), height=180,
        )
        st.plotly_chart(fig_rh, use_container_width=True, config={"displayModeBar": False})

    with col_fc:
        st.markdown('<div class="section-label">// 7-DAY ROUTE FORECAST</div>',
                    unsafe_allow_html=True)
        if st.button("📡 Load Forecast Chart", use_container_width=False):
            st.session_state["forecast_points"] = api_forecast()

        pts = st.session_state.get("forecast_points", [])
        if pts:
            times = [datetime.datetime.fromtimestamp(p["ts"]).strftime("%d %b %H:%M") for p in pts]
            temps = [p["temp"] for p in pts]
            fig_fc = go.Figure()
            fig_fc.add_trace(go.Scatter(
                x=times, y=temps, mode="lines+markers",
                line=dict(color="#00d4ff", width=2),
                marker=dict(color="#7c3aed", size=4),
                name="Forecast Temp",
                fill="tozeroy",
                fillcolor="rgba(0,212,255,0.06)",
            ))
            fig_fc.add_hline(
                y=target_temp, line_dash="dot", line_color="#10b981",
                annotation_text=f"Setpoint {target_temp:.1f}°C",
                annotation_font=dict(color="#10b981", size=9, family="Share Tech Mono"),
            )
            fig_fc.update_layout(
                paper_bgcolor="#04080f", plot_bgcolor="#0d1726",
                font=dict(family="Share Tech Mono", size=8, color="#94a3b8"),
                margin=dict(l=10, r=10, t=10, b=30), height=340,
                xaxis=dict(gridcolor="#1e3a5f", tickangle=-45, nticks=12),
                yaxis=dict(title="°C", gridcolor="#1e3a5f"),
                showlegend=False,
            )
            st.plotly_chart(fig_fc, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("""
            <div style="background:#0d1726; border:1px solid #1e3a5f; border-radius:6px;
                        padding:40px; text-align:center; color:#64748b;
                        font-family:'Share Tech Mono',monospace; font-size:0.8rem;">
              Press 'Load Forecast Chart' to display the 7-day route forecast.<br><br>
              First call /api/v1/weather/forecast via the 🔄 FORECAST button in the sidebar.
            </div>""", unsafe_allow_html=True)

else:
    # ── No result yet ──────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center; padding:60px; color:#64748b;
                font-family:'Share Tech Mono',monospace;">
      <div style="font-size:3rem; margin-bottom:14px;">🚢</div>
      <div style="color:#00d4ff; font-size:1rem; letter-spacing:0.1em;">MAR-HVAC AI READY</div>
      <div style="margin-top:8px; font-size:0.75rem;">
        Configure cabin parameters in the sidebar and press ⚡ CALCULATE
      </div>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────

st.markdown("""
<div style="margin-top:20px; text-align:center;
            font-family:'Share Tech Mono',monospace; font-size:0.6rem;
            color:#1e3a5f; border-top:1px solid #1e3a5f; padding-top:10px;">
  MAR-HVAC AI v2.0 &nbsp;|&nbsp; Week 3+4 + Req 1–7 Complete &nbsp;|&nbsp;
  ASHRAE + IMO 2030 &nbsp;|&nbsp; Ghost Cooling + Asset Defence + 7-Day Forecast + 11-Bar Breakdown
</div>
""", unsafe_allow_html=True)