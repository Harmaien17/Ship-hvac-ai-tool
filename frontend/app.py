"""
MAR-HVAC AI — Command Center Dashboard
frontend/app.py

MERGED FINAL VERSION — All Features Unified
UI THEME: Soft Maritime Daylight — pastel, white, purple, lively

Features merged from both versions:
  - Full AutoCAD PDF blueprint parser (v2 extended regex suite)
  - MAR-Chat AI explainer panel (rule-based, works offline)
  - ROI banner with CO₂ stats
  - 11-variable heat load breakdown bar chart
  - Asset Defence gauges (Dew Point + Humidity)
  - 14-Day anticipatory cooling forecast
  - Ghost Cooling / Corrosion / Mold / Emergency Heat mode badges
  - Starlink / weather / backend status indicators
  - HP Pavilion 4GB RAM optimised (local fallback engine)
  - 1080p polished layout — no overflow

Run with:
  cd frontend
  streamlit run app.py
"""

import os
import sys
import re
import time
from io import BytesIO
from typing import Optional

import streamlit as st
import requests
import plotly.graph_objects as go
import pandas as pd

# ── Optional PDF support (local, saves backend RAM) ──────────
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
API_TIMEOUT = 10

# ── DEMO MODE — False = live backend; True = always mock (screen recording only) ──
DEMO_MODE = False

st.set_page_config(
    page_title="MAR-HVAC AI",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
# AUTOCAD PDF PARSER  (full production version — runs locally)
# Merged: v1 simple regex + v2 extended patterns (mm, L×W,
# ceiling, window, material, u-value)
# ─────────────────────────────────────────────────────────────

def parse_ship_drawing_locally(pdf_bytes: bytes, cabin_hint: str = "") -> dict:
    """
    Full-featured ship drawing parser.
    Extracts: cabin_id, cabin_area_m2, window_area_m2,
              ceiling_height_m, wall_material, u_value_override.
    Falls back gracefully if pypdf is missing or PDF is image-only.
    """
    if not PYPDF_AVAILABLE:
        return {"success": False, "parse_notes": ["pypdf not installed. Run: pip install pypdf"]}

    try:
        reader    = PdfReader(BytesIO(pdf_bytes))
        full_text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
        full_text = full_text.strip()
    except Exception as e:
        return {"success": False, "parse_notes": [f"PDF read error: {e}"]}

    if not full_text:
        return {"success": False, "parse_notes": ["No text found — PDF may be a scanned image."]}

    notes  = []
    result = {
        "success":          False,
        "cabin_id":         "PARSED-CABIN",
        "cabin_area_m2":    None,
        "window_area_m2":   None,
        "ceiling_height_m": None,
        "wall_material":    None,
        "u_value_override": None,
        "parse_notes":      notes,
    }

    upper = full_text.upper()

    # ── Cabin ID ──────────────────────────────────────────────
    cabin_patterns = [
        r"(?:CABIN|ROOM|STATEROOM|COMPARTMENT)\s+([A-Z0-9\-]+)",
        r"([A-Z]{1,3}\-?\d{1,3})\s+(?:CABIN|ROOM|STATEROOM)",
    ]
    for pat in cabin_patterns:
        m = re.search(pat, upper)
        if m:
            result["cabin_id"] = f"CABIN-{m.group(1).strip()}"
            notes.append(f"Cabin ID: {result['cabin_id']}")
            break
    if cabin_hint:
        result["cabin_id"] = f"CABIN-{cabin_hint.upper()}"

    # ── Dimensions (3 strategies: L=x W=y, mmXmm, mXm) ───────
    m_lw = re.search(r"L\s*[=:]\s*(\d+\.?\d*)\s*.*?W\s*[=:]\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
    m_mm = re.search(r"(\d{3,5})\s*[xX×]\s*(\d{3,5})\s*(?:mm|MM)", full_text)
    m_mt = re.search(r"(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)\s*(?:m|M|metre|meter)?", full_text)

    # v1 simple fallback
    if not m_lw and not m_mm and not m_mt:
        m_mt = re.search(r"(\d+\.?\d*)\s*[X×]\s*(\d+\.?\d*)\s*M", upper)

    length_m = width_m = None
    if m_lw:
        length_m, width_m = float(m_lw.group(1)), float(m_lw.group(2))
        notes.append(f"L/W notation: {length_m}m × {width_m}m")
    elif m_mm:
        length_m, width_m = float(m_mm.group(1)) / 1000, float(m_mm.group(2)) / 1000
        notes.append(f"mm notation: {length_m}m × {width_m}m")
    elif m_mt:
        v1, v2 = float(m_mt.group(1)), float(m_mt.group(2))
        if 2.0 <= v1 <= 20.0 and 2.0 <= v2 <= 20.0:
            length_m, width_m = v1, v2
            notes.append(f"Metres: {length_m}m × {width_m}m")

    if length_m and width_m:
        result["cabin_area_m2"] = round(length_m * width_m, 2)
        result["success"]       = True
        notes.append(f"Area: {result['cabin_area_m2']} m²")

    # ── Ceiling height ────────────────────────────────────────
    m_h = re.search(
        r"(?:H|HEIGHT|CEILING|CLEAR)\s*[=:\s]\s*(\d+\.?\d*)\s*(?:m|M|mm|MM)?",
        full_text, re.IGNORECASE)
    if m_h:
        h = float(m_h.group(1))
        if h > 10:
            h /= 1000
        if 1.8 <= h <= 5.0:
            result["ceiling_height_m"] = round(h, 2)
            notes.append(f"Ceiling: {h}m")

    # ── Window / porthole area ────────────────────────────────
    m_win = re.search(
        r"(?:WINDOW|PORTHOLE|GLAZING)\s+(?:AREA\s+)?[=:\s]?\s*(\d+\.?\d*)\s*(?:m2|M2|SQM)?",
        full_text, re.IGNORECASE)
    if not m_win:
        # v1 simple fallback
        m_win = re.search(r"(?:WINDOW|PORTHOLE)\s*[:=]\s*(\d+\.?\d*)", upper)
    if m_win:
        wa = float(m_win.group(1))
        if wa > 50:
            wa /= 10000
        if 0.01 <= wa <= 10.0:
            result["window_area_m2"] = round(wa, 3)
            notes.append(f"Window: {wa} m²")

    # ── Wall material & U-value ───────────────────────────────
    materials = {
        "steel":      ("steel",        2.5),
        "aluminum":   ("aluminum",     1.8),
        "aluminium":  ("aluminium",    1.8),
        "composite":  ("composite",    0.8),
        "insulated":  ("insulated",    0.65),
        "mineral":    ("mineral wool", 0.55),
    }
    for kw, (mat, uval) in materials.items():
        if kw in full_text.lower():
            result["wall_material"]    = mat
            result["u_value_override"] = uval
            notes.append(f"Material: {mat} (U={uval})")
            break

    return result


# ─────────────────────────────────────────────────────────────
# MAR-CHAT  (rule-based HVAC explainer — no API keys needed)
# Merged: v1 basic Q&A + v2 extended with dew point, ROI, CO₂
# ─────────────────────────────────────────────────────────────

def ask_mar_chat_local(question: str, last_decision: Optional[dict]) -> str:
    if not last_decision:
        return "No HVAC data yet. Press ⚡ CALCULATE first, then ask your question."

    q     = question.lower()
    mode  = last_decision.get("mode", "UNKNOWN")
    load  = last_decision.get("optimized_load_kw", 0)
    sav   = last_decision.get("energy_saved_percent", 0)
    dew   = last_decision.get("dew_point", 0)
    warns = last_decision.get("warnings", [])
    cid   = last_decision.get("cabin_id", "the cabin")
    roi   = last_decision.get("annual_roi_inr", None)
    co2   = last_decision.get("co2_saved_hr_kg", None)

    # Why / reason / trigger
    if any(w in q for w in ["why", "reason", "cause", "trigger"]):
        if mode == "MAINTENANCE_COOLING":
            return (f"{cid} is in Ghost Cooling — PIR sensor shows cabin is empty. "
                    f"Load reduced to {100-sav:.0f}% of full capacity, saving {sav:.0f}% energy "
                    f"while preventing mold and corrosion.")
        if mode == "CORROSION_PREVENTION":
            return (f"{cid} triggered Corrosion Prevention — internal temp is near dew point "
                    f"({dew:.1f}°C). Condensation on steel hull accelerates corrosion. "
                    f"Fans running at 30% to circulate air.")
        if mode == "MOLD_ALERT":
            return (f"{cid} is in Mold Alert — humidity exceeded safe threshold in an empty cabin. "
                    f"Dehumidification cycle is now active.")
        if mode == "EMERGENCY_HEAT":
            return (f"{cid} switched to heating — external temperature dropped below setpoint. "
                    f"Arctic/cold route detected. System supplying heat for crew comfort.")
        if mode == "FULL_COOLING":
            return (f"{cid} is at full cooling — calculated heat load is near max thermal capacity. "
                    f"High external temp, direct solar gain, occupant heat, and equipment load all contribute.")
        return f"System is in {mode.replace('_',' ')} based on current thermal gradients and occupancy status."

    # Energy / savings / ROI
    if any(w in q for w in ["save", "saving", "roi", "money", "cost", "energy"]):
        roi_line = f" Annual ROI: ₹{roi:,.0f}." if roi else ""
        co2_line = f" CO₂ saved: {co2} kg/hr." if co2 else ""
        return (f"Saving {sav:.1f}% vs full load. Optimised at {load:.3f} kW.{roi_line}{co2_line} "
                f"Ghost Cooling is the primary saving mechanism for empty cabins (40–50% reduction).")

    # Safety / status
    if any(w in q for w in ["safe", "ok", "normal", "fine", "status"]):
        if warns:
            return f"Attention required: {warns[0]}"
        return (f"{cid} operating normally in {mode.replace('_', ' ')} mode at {load:.3f} kW. "
                f"No warnings. All readings within safe limits.")

    # Default
    return (f"{cid} → {mode.replace('_', ' ')} mode at {load:.3f} kW ({sav:.0f}% saved). "
            f"Ask me: why this mode, energy savings, ROI, corrosion risk, or safety status.")


# ─────────────────────────────────────────────────────────────
# CSS — SOFT MARITIME DAYLIGHT + 1080p POLISH
# Merged: v1 foundations + v2 complete design system
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Nunito:wght@400;600;700;800;900&display=swap');

  :root {
    --bg:        #e8eef8;
    --panel:     #ffffff;
    --surface:   #f2f6fc;
    --border:    #c8d8f0;
    --border2:   #a8c0e0;
    --ocean:     #1e80cc;
    --sky:       #6ab8e8;
    --seafoam:   #18b098;
    --mint:      #6ed8b0;
    --coral:     #f07050;
    --peach:     #f8a888;
    --lavender:  #9888d8;
    --sunflower: #f8c820;
    --purple:    #7a4fc0;
    --purple-lt: #e0d4f8;
    --purple-md: #9880d8;
    --green:     #20a868;
    --amber:     #d08000;
    --red:       #c83048;
    --blue:      #2a68e0;
    --text:      #1a2840;
    --text2:     #385070;
    --muted:     #5878a8;
    --mono:      'DM Mono', monospace;
    --ui:        'Nunito', sans-serif;
    --shadow-sm: 0 1px 4px rgba(122,79,192,0.10);
    --shadow-md: 0 4px 16px rgba(122,79,192,0.14);
    --shadow-lg: 0 8px 32px rgba(122,79,192,0.20);
  }

  /* ── Base ── */
  html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: var(--ui) !important;
  }
  [data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image: radial-gradient(circle, #a8c0e0 1px, transparent 1px);
    background-size: 28px 28px;
    opacity: 0.28;
    pointer-events: none;
    z-index: 0;
  }
  [data-testid="stSidebar"] {
    background: var(--panel) !important;
    border-right: 1.5px solid var(--border) !important;
    box-shadow: 2px 0 12px rgba(122,79,192,0.08) !important;
  }
  [data-testid="stHeader"] { background: transparent !important; }

  /* ── Typography ── */
  h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: var(--ui) !important;
    color: var(--text) !important;
    font-weight: 800 !important;
  }
  label, p, .stMarkdown p, .stSlider label {
    font-family: var(--ui) !important;
    color: var(--text2) !important;
    font-weight: 600 !important;
  }
  [data-testid="stSidebar"] label {
    color: var(--text2) !important;
    font-weight: 700 !important;
    font-size: 0.80rem !important;
  }

  /* ── Controls ── */
  .stSlider [data-baseweb="slider"] [role="slider"] {
    background: var(--purple) !important;
    border-color: var(--purple) !important;
    box-shadow: 0 0 0 4px rgba(122,79,192,0.22) !important;
  }
  .stButton > button {
    background: linear-gradient(135deg, var(--purple), var(--ocean)) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: var(--ui) !important;
    font-size: 0.80rem !important;
    font-weight: 800 !important;
    letter-spacing: 0.04em !important;
    box-shadow: var(--shadow-sm) !important;
    transition: opacity 0.15s, box-shadow 0.15s !important;
  }
  .stButton > button:hover {
    opacity: 0.9 !important;
    box-shadow: var(--shadow-md) !important;
  }
  .stSelectbox > div > div,
  .stTextInput > div > div > input,
  .stNumberInput > div > div > input,
  .stTextArea textarea {
    background: var(--surface) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    font-family: var(--mono) !important;
    font-size: 0.82rem !important;
  }
  .stCheckbox label, .stToggle label {
    color: var(--text2) !important;
    font-weight: 700 !important;
  }
  hr { border-color: var(--border) !important; }

  /* ── ROI Banner ── */
  .roi-banner {
    background: linear-gradient(120deg, #f0eaff, #e8f8f0);
    border: 1.5px solid #c8d8f0;
    border-left: 5px solid var(--purple);
    border-radius: 12px;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 18px;
    box-shadow: var(--shadow-sm);
    margin-bottom: 14px;
  }
  .roi-banner-icon { font-size: 1.8rem; line-height: 1; }
  .roi-banner-text {
    font-family: var(--ui);
    font-size: 1.05rem;
    font-weight: 900;
    color: var(--purple);
    letter-spacing: 0.01em;
  }
  .roi-banner-sub {
    font-family: var(--mono);
    font-size: 0.68rem;
    color: var(--muted);
    margin-top: 2px;
    letter-spacing: 0.06em;
  }

  /* ── Decision log ── */
  .decision-log {
    background: #f0eeff;
    border: 1.5px solid #c8d8f0;
    border-left: 4px solid var(--purple);
    border-radius: 10px;
    padding: 12px 14px;
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    line-height: 1.75;
    color: var(--text2);
    max-height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .decision-log .log-header  { color: var(--purple); font-weight: 500; }
  .decision-log .log-warn    { color: var(--amber); }
  .decision-log .log-error   { color: var(--red); }
  .decision-log .log-ok      { color: var(--green); }
  .decision-log .log-section { color: var(--seafoam); }

  /* ── MAR-Chat ── */
  .mar-chat-box {
    background: #f8f5ff;
    border: 1.5px solid #c8d8f0;
    border-left: 4px solid var(--ocean);
    border-radius: 10px;
    padding: 12px 14px;
    font-family: 'DM Mono', monospace;
    font-size: 0.74rem;
    line-height: 1.8;
    color: var(--text2);
    min-height: 80px;
    white-space: pre-wrap;
  }

  /* ── Alert variants (small utility) ── */
  .alert-red {
    background: rgba(200,48,72,0.08);
    border: 1.5px solid rgba(200,48,72,0.35);
    border-left: 4px solid var(--red);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: var(--ui);
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--red);
    margin: 5px 0;
  }
  .alert-amber {
    background: rgba(208,128,0,0.08);
    border: 1.5px solid rgba(208,128,0,0.35);
    border-left: 4px solid var(--amber);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: var(--ui);
    font-size: 0.82rem;
    font-weight: 700;
    color: #a06000;
    margin: 5px 0;
  }
  .alert-blue {
    background: rgba(42,104,224,0.08);
    border: 1.5px solid rgba(42,104,224,0.35);
    border-left: 4px solid var(--blue);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: var(--ui);
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--blue);
    margin: 5px 0;
  }

  /* ── BIG WARNING BANNERS — Corrosion & Mold ── */
  @keyframes warningPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(200,48,72,0.0), 0 6px 28px rgba(200,48,72,0.22); }
    50%       { box-shadow: 0 0 0 6px rgba(200,48,72,0.12), 0 6px 28px rgba(200,48,72,0.32); }
  }
  @keyframes moldPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(208,128,0,0.0), 0 6px 28px rgba(208,128,0,0.22); }
    50%       { box-shadow: 0 0 0 6px rgba(208,128,0,0.12), 0 6px 28px rgba(208,128,0,0.32); }
  }
  @keyframes flashStripe {
    0%   { background-position: 0 0; }
    100% { background-position: 40px 0; }
  }

  .warning-banner-corrosion {
    position: relative;
    overflow: hidden;
    background: linear-gradient(135deg, #fff0f2 60%, #fde0e6);
    border: 2px solid #e8405a;
    border-left: 7px solid #c83048;
    border-radius: 14px;
    padding: 0;
    margin: 8px 0 12px 0;
    animation: warningPulse 2s ease-in-out infinite;
  }
  .warning-banner-corrosion::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: repeating-linear-gradient(
      90deg,
      #c83048 0px, #c83048 16px,
      #f0a0b0 16px, #f0a0b0 32px
    );
    animation: flashStripe 0.8s linear infinite;
  }
  .warning-banner-corrosion .wb-inner {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 20px 14px 20px;
  }
  .warning-banner-corrosion .wb-icon {
    font-size: 2.6rem;
    line-height: 1;
    flex-shrink: 0;
    filter: drop-shadow(0 2px 6px rgba(200,48,72,0.4));
  }
  .warning-banner-corrosion .wb-title {
    font-family: 'Nunito', sans-serif;
    font-size: 1.05rem;
    font-weight: 900;
    color: #a01830;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .warning-banner-corrosion .wb-msg {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #803040;
    margin-top: 3px;
    line-height: 1.6;
  }
  .warning-banner-corrosion .wb-badge {
    margin-left: auto;
    flex-shrink: 0;
    font-family: 'Nunito', sans-serif;
    font-size: 0.60rem;
    font-weight: 900;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    background: #c83048;
    color: #fff;
    padding: 5px 14px;
    border-radius: 20px;
    white-space: nowrap;
  }

  .warning-banner-mold {
    position: relative;
    overflow: hidden;
    background: linear-gradient(135deg, #fffbf0 60%, #fff3d0);
    border: 2px solid #d08000;
    border-left: 7px solid #b06800;
    border-radius: 14px;
    padding: 0;
    margin: 8px 0 12px 0;
    animation: moldPulse 2.4s ease-in-out infinite;
  }
  .warning-banner-mold::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: repeating-linear-gradient(
      90deg,
      #d08000 0px, #d08000 16px,
      #f8e080 16px, #f8e080 32px
    );
    animation: flashStripe 1s linear infinite;
  }
  .warning-banner-mold .wb-inner {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 20px 14px 20px;
  }
  .warning-banner-mold .wb-icon {
    font-size: 2.6rem;
    line-height: 1;
    flex-shrink: 0;
    filter: drop-shadow(0 2px 6px rgba(208,128,0,0.4));
  }
  .warning-banner-mold .wb-title {
    font-family: 'Nunito', sans-serif;
    font-size: 1.05rem;
    font-weight: 900;
    color: #7a4a00;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .warning-banner-mold .wb-msg {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #6a4000;
    margin-top: 3px;
    line-height: 1.6;
  }
  .warning-banner-mold .wb-badge {
    margin-left: auto;
    flex-shrink: 0;
    font-family: 'Nunito', sans-serif;
    font-size: 0.60rem;
    font-weight: 900;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    background: #d08000;
    color: #fff;
    padding: 5px 14px;
    border-radius: 20px;
    white-space: nowrap;
  }

  /* ── Load box ── */
  .load-box {
    background: linear-gradient(145deg, #ffffff, #ede8ff);
    border: 1.5px solid var(--border);
    border-top: 4px solid var(--purple);
    border-radius: 14px;
    padding: 18px 16px;
    text-align: center;
    box-shadow: var(--shadow-md);
  }
  .load-box.heating-mode {
    border-top-color: var(--blue) !important;
    background: linear-gradient(145deg, #ffffff, #eef2ff) !important;
  }
  .load-number {
    font-family: 'DM Mono', monospace;
    font-size: 3.4rem;
    font-weight: 500;
    color: var(--purple);
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .load-number.heating { color: var(--blue); }
  .load-unit {
    font-family: var(--ui);
    font-size: 0.82rem;
    color: var(--muted);
    font-weight: 600;
    margin-top: 3px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  /* ── Mode badge ── */
  .mode-badge {
    display: inline-block;
    font-family: var(--ui);
    font-size: 0.65rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    padding: 4px 12px;
    border-radius: 20px;
    margin-top: 10px;
    text-transform: uppercase;
  }
  .mode-FULL_COOLING         { color:#c83048; background:#fde8ec; border:1.5px solid #f0a0b0; }
  .mode-REDUCED_COOLING      { color:#0e7868; background:#d0f5f0; border:1.5px solid #80d8d0; }
  .mode-MAINTENANCE_COOLING  { color:#906000; background:#fff0c0; border:1.5px solid #f0c840; }
  .mode-STANDBY              { color:#906000; background:#fff0c0; border:1.5px solid #f0c840; } /* Ghost Cooling */
  .mode-FAILSAFE             { color:#c83048; background:#fde8ec; border:1.5px solid #f0a0b0; }
  .mode-EMERGENCY_HEAT       { color:#1848b8; background:#d8e8ff; border:1.5px solid #90b8f0; }
  .mode-CORROSION_PREVENTION { color:#c83048; background:#fde8ec; border:1.5px solid #f0a0b0; }
  .mode-MOLD_ALERT           { color:#906000; background:#fff0c0; border:1.5px solid #f0c840; }

  /* ── Savings box ── */
  .savings-box {
    background: linear-gradient(145deg, #ffffff, #edfdf5);
    border: 1.5px solid var(--border);
    border-top: 4px solid var(--green);
    border-radius: 14px;
    padding: 16px;
    text-align: center;
    box-shadow: var(--shadow-md);
  }
  .savings-number {
    font-family: 'DM Mono', monospace;
    font-size: 2.4rem;
    font-weight: 500;
    color: var(--green);
    letter-spacing: -0.02em;
  }

  /* ── Metric cards ── */
  .metric-box {
    background: white;
    border: 1.5px solid var(--border);
    border-radius: 12px;
    padding: 12px 14px;
    text-align: center;
    box-shadow: var(--shadow-sm);
  }
  .metric-val {
    font-family: 'DM Mono', monospace;
    font-size: 1.55rem;
    font-weight: 700;
    color: var(--purple);
  }
  .metric-lbl {
    font-family: var(--ui);
    font-size: 0.68rem;
    color: var(--muted);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 3px;
  }

  /* ── Status rows ── */
  .status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 5px 10px;
    background: var(--panel);
    border: 1.5px solid var(--border);
    border-radius: 7px;
    margin: 2px 0;
    font-family: 'DM Mono', monospace;
    font-size: 0.73rem;
    box-shadow: var(--shadow-sm);
  }
  .label-muted { color: var(--muted); }

  /* ── Section labels ── */
  .section-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.56rem;
    color: var(--purple);
    letter-spacing: 0.22em;
    text-transform: uppercase;
    border-bottom: 1.5px solid #e8e0f5;
    padding-bottom: 4px;
    margin-bottom: 10px;
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--purple-md); border-radius: 10px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def api_optimize(payload: dict) -> Optional[dict]:
    if DEMO_MODE:
        return None  # force mock fallback
    try:
        r = requests.post(f"{BACKEND_URL}/api/v1/optimize", json=payload, timeout=API_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        st.session_state["api_error"] = str(e)
        return None


def api_health() -> Optional[dict]:
    if DEMO_MODE:
        return None  # force offline badge
    try:
        return requests.get(f"{BACKEND_URL}/api/v1/health", timeout=3).json()
    except Exception:
        return None


def api_forecast() -> list:
    """Fetch forecast chart points — tries backend first, falls back to local generation."""
    # Try backend chart endpoint first
    try:
        r = requests.get(f"{BACKEND_URL}/api/v1/weather/forecast/chart", timeout=6)
        r.raise_for_status()
        pts = r.json().get("points", [])
        if pts:
            return pts
    except Exception:
        pass
    # Local fallback: generate 14-day simulated route forecast
    import time as _time
    now = int(_time.time())
    pts = []
    for i in range(14):
        pts.append({
            "ts":       now + (i * 86400),
            "temp":     round(28.0 + (i % 3) - (i * 0.2), 1),
            "humidity": 65 + (i % 5),
        })
    return pts


def run_local_engine(payload: dict) -> dict:
    """
    Attempts to import and run the HVAC engine directly from the
    backend package — zero network, zero latency.
    """
    try:
        backend_path = os.path.join(os.path.dirname(__file__), "..", "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from schemas import CabinTelemetry as CT
        from hvac_engine import calculate_optimized_load
        return calculate_optimized_load(CT(**payload)).model_dump()
    except Exception as e:
        return {"error": str(e)}


def mock_fallback(payload: dict) -> dict:
    """
    Local mock engine — computes dynamic values from the real payload
    so readings update when sliders change, even with no backend.
    """
    import math

    cabin_id     = payload.get("cabin_id", "CABIN-A3")
    int_temp     = payload.get("internal_temp", 26.0)
    ext_temp     = payload.get("external_temp") or 34.0
    rh           = payload.get("internal_humidity", 68.0)
    area         = payload.get("cabin_area_m2", 25.0)
    win_area     = payload.get("window_area_m2", 1.5)
    equip_w      = payload.get("equipment_wattage", 450.0)
    occ_count    = payload.get("occupant_count", 0)
    occupied     = payload.get("occupancy", False)
    target       = payload.get("target_temp", 22.0)
    solar        = payload.get("solar_irradiance") or 650.0
    sunlight     = payload.get("direct_sunlight", False)
    heat_hull    = payload.get("heat_soaked_hull", False)
    eng_adj      = payload.get("engine_adjacent", False)
    ceil_area    = payload.get("ceiling_area_exposed_m2", 0.0)
    floor_area   = payload.get("floor_area_exposed_m2", 0.0)
    market       = payload.get("market_segment", "cargo")

    # Simple thermodynamic estimates (ASHRAE-approximate)
    delta_t          = max(ext_temp - target, 0)
    q_transmission   = round(area * 2.5 * delta_t / 1000, 3)
    q_solar          = round((solar * win_area * 0.87 * (1.3 if sunlight else 0.6)) / 1000, 3)
    q_fenestration   = round(win_area * 5.8 * delta_t / 1000, 3)
    q_metabolic      = round(occ_count * 75 / 1000, 3)
    q_equipment      = round(equip_w * 0.8 / 1000, 3)
    q_engine_radiant = round((area * 0.4 if eng_adj else 0) / 1000, 3)
    q_thermal_lag    = round(area * 0.3 * (1.5 if heat_hull else 0.6) / 1000, 3)
    q_ceiling        = round(ceil_area * 2.0 * delta_t / 1000, 3)
    q_floor          = round(floor_area * 1.5 * delta_t / 1000, 3)
    # Magnus formula dew point
    a, b = 17.27, 237.7
    alpha   = (a * int_temp / (b + int_temp)) + math.log(max(rh, 1) / 100.0)
    dew_pt  = round((b * alpha) / (a - alpha), 2)
    q_latent = round(area * rh * 0.012 / 1000, 3)
    heating_kw = round(max(target - ext_temp, 0) * area * 0.03 / 1000, 3)

    q_total = q_transmission + q_solar + q_fenestration + q_metabolic + \
              q_equipment + q_engine_radiant + q_thermal_lag + q_ceiling + \
              q_floor + q_latent + heating_kw

    # Mode selection
    margin = int_temp - dew_pt
    mold_thresh = {"cargo":70,"cruise":65,"navy":60,"hospital":55,"yacht":60}.get(market, 70)

    if ext_temp < target - 3:
        mode, savings = "EMERGENCY_HEAT", 0.0
        load_kw = heating_kw
    elif not occupied and rh > mold_thresh:
        mode, savings = "MOLD_ALERT", 30.0
        load_kw = round(q_total * 0.7, 3)
    elif margin < 2.0:
        mode, savings = "CORROSION_PREVENTION", 20.0
        load_kw = round(q_total * 0.8, 3)
    elif not occupied:
        mode, savings = "MAINTENANCE_COOLING", 45.0
        load_kw = round(q_total * 0.55, 3)
    elif q_total > 3.5:
        mode, savings = "FULL_COOLING", 0.0
        load_kw = round(q_total, 3)
    else:
        mode, savings = "REDUCED_COOLING", 20.0
        load_kw = round(q_total * 0.8, 3)

    load_kw = max(load_kw, 0.001)
    hrs_per_year  = 8760
    kwh_saved     = (q_total - load_kw) * hrs_per_year
    roi_inr       = round(kwh_saved * 9.5, 0)
    co2_kg        = round((q_total - load_kw) * 0.82, 3)

    warnings = []
    if margin < 2.0:
        warnings.append(f"CORROSION RISK: Temp-Dew margin only {margin:.1f}°C — condensation imminent")
    if rh > mold_thresh:
        warnings.append(f"MOLD ALERT: Humidity {rh:.0f}% exceeds {mold_thresh}% threshold")

    return {
        "mode": mode,
        "cabin_id": cabin_id,
        "optimized_load_kw": load_kw,
        "energy_saved_percent": savings,
        "annual_roi_inr": roi_inr,
        "co2_saved_hr_kg": co2_kg,
        "setpoint_actual": target,
        "weather_source": "local-mock",
        "dew_point": dew_pt,
        "warnings": warnings,
        "decision_log": [
            f"=== MAR-HVAC LOCAL ENGINE — {cabin_id} ===",
            f"--- Ext: {ext_temp}°C  Int: {int_temp}°C  RH: {rh}%  Area: {area}m² ---",
            f"--- ΔT={delta_t:.1f}°C  Solar={solar}W/m²  Occ={occ_count} ---",
            f"q_transmission={q_transmission}kW  q_solar={q_solar}kW  q_latent={q_latent}kW",
            f"q_equipment={q_equipment}kW  q_metabolic={q_metabolic}kW",
            f"q_total_raw={round(q_total,3)}kW",
            f"Dew Point={dew_pt}°C  Margin={margin:.1f}°C",
            f"FINAL MODE: {mode}  Load={load_kw}kW  Saved={savings:.0f}%",
            f"OK: Annual ROI ₹{roi_inr:,.0f}  CO₂ {co2_kg}kg/hr",
        ],
        "breakdown": {
            "q_transmission":   q_transmission,
            "q_solar":          q_solar,
            "q_fenestration":   q_fenestration,
            "q_metabolic":      q_metabolic,
            "q_equipment":      q_equipment,
            "q_engine_radiant": q_engine_radiant,
            "q_thermal_lag":    q_thermal_lag,
            "q_ceiling":        q_ceiling,
            "q_floor_conduction": q_floor,
            "q_latent":         q_latent,
            "heating_load_kw":  heating_kw,
        },
    }


def colorise_log(lines: list) -> str:
    out = []
    for line in lines:
        e = line.replace("<", "&lt;").replace(">", "&gt;")
        if "===" in line or "FINAL" in line:
            out.append(f'<span class="log-header">{e}</span>')
        elif any(x in line for x in ["!", "ALERT", "RISK", "FAILSAFE", "STALE", "CRITICAL", "CORROSION", "MOLD"]):
            out.append(f'<span class="log-warn">{e}</span>')
        elif any(x in line for x in ["OK:", "saved", "Saved"]):
            out.append(f'<span class="log-ok">{e}</span>')
        elif "---" in line:
            out.append(f'<span class="log-section">{e}</span>')
        else:
            out.append(e)
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────

for key, default in [
    ("result", None),
    ("api_error", None),
    ("backend_mode", "unknown"),
    ("forecast_points", []),
    ("chat_response", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────────────────────
# STARLINK / BACKEND STATUS
# ─────────────────────────────────────────────────────────────

starlink_status = "⚠️ Backend Offline"
starlink_color  = "#c83048"
starlink_bg     = "#fde8ec"
cache_age_label = ""

try:
    if DEMO_MODE:
        raise Exception("demo mode")
    health_res = requests.get(f"{BACKEND_URL}/api/v1/health", timeout=2).json()
    if health_res.get("starlink_active"):
        starlink_status = "🟢 Starlink: Live"
        starlink_color  = "#20a868"
        starlink_bg     = "#c8f0e0"
    else:
        starlink_status = "🟡 Starlink: Offline — Local Cache"
        starlink_color  = "#d08000"
        starlink_bg     = "#fff0c0"
        cache_age_label = f"Cache Age: {health_res.get('cache_age_hours', '?')} hrs"
except Exception:
    pass


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding:10px 0 14px; border-bottom:1.5px solid #c8d8f0; margin-bottom:14px;">
      <div style="font-size:1.8rem; margin-bottom:3px;">🚢</div>
      <div style="font-family:'Nunito',sans-serif; font-size:1.05rem; font-weight:900;
                  color:#7a4fc0; letter-spacing:0.05em;">MAR-HVAC AI</div>
      <div style="font-family:'DM Mono',monospace; font-size:0.52rem; color:#5878a8;
                  letter-spacing:0.22em; margin-top:2px;">COMMAND CENTER v2.0</div>
    </div>""", unsafe_allow_html=True)

    # Status pill hidden for screen recording — logic & variables preserved above
    pass

    st.markdown("---")

    # ── AutoCAD Parser ────────────────────────────────────────
    st.markdown('<div class="section-label">📐 AutoCAD Blueprint Parser</div>', unsafe_allow_html=True)
    drawing     = st.file_uploader("Upload Ship Drawing (PDF or DWG)", type=["pdf", "dwg"])
    parsed_area = 25.0
    parsed_id   = "CABIN-A3"
    parsed_win  = 1.5

    if drawing:
        fname = drawing.name.lower()
        if fname.endswith(".dwg"):
            # DWG is binary — send to backend /analyze/blueprint which handles it
            st.info("📐 DWG file detected — sending to backend parser…")
            try:
                form_data = {
                    "cabin_id":       (None, cabin_id if "cabin_id" in dir() else "CABIN-A3"),
                    "internal_temp":  (None, "26.0"),
                    "internal_rh":    (None, "68.0"),
                    "market_segment": (None, "cargo"),
                }
                files = {"drawing": (drawing.name, drawing.read(), "application/octet-stream")}
                r = requests.post(
                    f"{BACKEND_URL}/api/v1/analyze/blueprint",
                    data={k: v[1] for k, v in form_data.items()},
                    files=files,
                    timeout=15,
                )
                if r.status_code == 200:
                    bp = r.json().get("blueprint_variables", {})
                    parsed_area = bp.get("cabin_area_m2") or parsed_area
                    parsed_win  = bp.get("window_area_m2") or parsed_win
                    parsed_id   = r.json().get("cabin_id", parsed_id)
                    st.success(f"✅ DWG parsed via backend — {parsed_id}")
                else:
                    st.warning(f"Backend returned {r.status_code}. Enter dimensions manually.")
            except Exception as e:
                st.warning(f"Backend unreachable for DWG ({e}). Enter dimensions manually below.")

        elif fname.endswith(".pdf"):
            if not PYPDF_AVAILABLE:
                st.error("Run: pip install pypdf")
            else:
                with st.spinner("Parsing blueprint locally…"):
                    d_res = parse_ship_drawing_locally(drawing.read())
                    if d_res["success"]:
                        parsed_area = d_res["cabin_area_m2"]
                        parsed_id   = d_res["cabin_id"]
                        parsed_win  = d_res.get("window_area_m2") or parsed_win
                        notes_str   = " · ".join(d_res.get("parse_notes", []))
                        st.success(f"✅ {parsed_id} — {parsed_area} m²")
                        if notes_str:
                            st.caption(notes_str)
                    else:
                        st.warning("Could not extract dimensions. Enter manually below.")
                        for n in d_res.get("parse_notes", []):
                            st.caption(f"• {n}")
        else:
            st.error("Unsupported file type. Please upload a .pdf or .dwg file.")

    st.markdown("---")

    # ── Cabin Geometry ────────────────────────────────────────
    st.markdown("##### 🛏️ Cabin Geometry")
    cabin_id    = st.text_input("Cabin ID", value=parsed_id)
    cabin_area  = st.slider("Floor Area (m²)", 0.0, 2000.0, float(parsed_area), 5.0)
    ship_length = st.slider("Ship Length (m)", 0, 500, 120)
    window_area = st.slider("Window Area (m²)", 0.0, 50.0, float(parsed_win), 0.5)
    target_temp = st.slider("Target Setpoint (°C)", 18.0, 28.0, 22.0, 0.5)
    cabin_side  = st.selectbox("Vessel Side", ["interior", "starboard", "port", "bow", "stern"], index=0)
    market      = st.selectbox("Vessel Type", ["cargo", "cruise", "navy", "hospital", "yacht"], index=0)

    st.markdown("---")
    st.markdown("##### 📡 Sensors (DHT22 + PIR)")
    occupancy     = st.toggle("🧍 Occupied (PIR)", value=False)
    occ_count     = st.number_input("Occupant Count", min_value=0, max_value=100,
                                     value=2 if occupancy else 0)
    internal_temp = st.slider("Internal Temp °C", 15.0, 42.0, 26.0, 0.5)
    internal_rh   = st.slider("Humidity % (DHT22)", 30.0, 98.0, 68.0, 1.0)

    st.markdown("---")
    st.markdown("##### ⚙️ Load Factors")
    equip_watts = st.number_input("Equipment Watts", min_value=0, max_value=10000, value=450)
    ceil_area   = st.slider("Sun-Exposed Ceiling (m²)", 0.0, float(max(cabin_area, 10.0)), 10.0)
    floor_area  = st.slider("Floor above Heat Source (m²)", 0.0, float(max(cabin_area, 10.0)), 5.0)

    st.markdown("---")
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
    st.markdown("##### 🌊 Ship Dynamics")
    direct_sunlight  = st.toggle("☀️ Direct Sunlight",  value=False)
    heat_soaked_hull = st.toggle("🔥 Heat-Soaked Hull", value=False)
    engine_adjacent  = st.toggle("⚙️ Engine Adjacent",  value=False)

    st.markdown("---")
    col_run, col_ref = st.columns(2)
    with col_run:
        run_btn = st.button("⚡ CALCULATE", use_container_width=True)
    with col_ref:
        fc_btn  = st.button("🔄 FORECAST",  use_container_width=True)
    st.caption(f"Backend: `{BACKEND_URL}`")


# ─────────────────────────────────────────────────────────────
# PAYLOAD
# ─────────────────────────────────────────────────────────────

payload = {
    "cabin_id":                cabin_id,
    "market_segment":          market,
    "cabin_side":              cabin_side,
    "target_temp":             target_temp,
    "cabin_area_m2":           cabin_area,
    "ship_length_m":           ship_length,
    "window_area_m2":          window_area,
    "occupancy":               occupancy,
    "occupant_count":          occ_count,
    "internal_temp":           internal_temp,
    "internal_humidity":       internal_rh,
    "external_temp":           external_temp if manual_weather else None,
    "solar_irradiance":        solar_irradiance if manual_weather else None,
    "direct_sunlight":         direct_sunlight,
    "heat_soaked_hull":        heat_soaked_hull,
    "engine_adjacent":         engine_adjacent,
    "equipment_wattage":       equip_watts,
    "ceiling_area_exposed_m2": ceil_area,
    "floor_area_exposed_m2":   floor_area,
}


# ─────────────────────────────────────────────────────────────
# CALCULATION ENGINE  (API → Local → Mock fallback chain)
# ─────────────────────────────────────────────────────────────

def calculate():
    result = api_optimize(payload)
    if result and "mode" in result:
        st.session_state["backend_mode"] = "api"
        st.session_state["result"]       = result
        st.session_state["api_error"]    = None
        return
    # Try local engine (imports backend hvac_engine directly)
    result = run_local_engine(payload)
    if "mode" in result:
        st.session_state["backend_mode"] = "local"
        st.session_state["result"]       = result
        return
    # Dynamic mock fallback — computes from real slider values
    st.session_state["backend_mode"] = "offline"
    st.session_state["result"]       = mock_fallback(payload)


if run_btn:
    # Always recalculate when button pressed — fresh payload every time
    with st.spinner("Analysing thermal dynamics…"):
        calculate()
elif st.session_state["result"] is None:
    # First load only
    with st.spinner("Analysing thermal dynamics…"):
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
        # Backend offline — generate forecast locally so chart still works
        st.sidebar.info("Backend offline — using local forecast buffer")


# ─────────────────────────────────────────────────────────────
# HEADER BAR
# ─────────────────────────────────────────────────────────────

health   = api_health()
bm       = st.session_state["backend_mode"]
bm_color = {"api": "#20a868", "local": "#d08000", "offline": "#c83048"}.get(bm, "#5878a8")
bm_bg    = {"api": "#c8f0e0", "local": "#fff0c0", "offline": "#fde8ec"}.get(bm, "#e8eef8")
bm_label = {"api": "● BACKEND LIVE", "local": "◈ LOCAL ENGINE", "offline": "○ OFFLINE (MOCK)"}.get(bm, "?")

weather_label = "○ NO WEATHER"
weather_color = "#5878a8"
weather_bg    = "#e8eef8"
if health:
    wc = health.get("weather_cache", {})
    fb = health.get("forecast_buffer", {})
    if wc.get("status") == "cache":
        weather_label = f"● LIVE {wc.get('temp_c', '?')}°C"
        weather_color = "#20a868"
        weather_bg    = "#c8f0e0"
    elif fb.get("available"):
        weather_label = f"◈ FORECAST {fb.get('age_hours', '?'):.0f}h OLD"
        weather_color = "#d08000"
        weather_bg    = "#fff0c0"
    else:
        weather_label = "○ FAILSAFE"
        weather_color = "#c83048"
        weather_bg    = "#fde8ec"

st.markdown(f"""
<div style="background:linear-gradient(120deg,#ffffff 55%,#f0eaff);
            border:1.5px solid #c8d8f0; border-left:5px solid #7a4fc0;
            border-radius:12px; padding:14px 20px; margin-bottom:14px;
            display:flex; justify-content:space-between; align-items:center;
            box-shadow:0 4px 20px rgba(122,79,192,0.12);">
  <div>
    <div style="font-family:'Nunito',sans-serif; font-size:1.25rem; font-weight:900;
                color:#5a3898; letter-spacing:0.02em;">🚢 MAR-HVAC AI — COMMAND CENTER</div>
    <div style="font-family:'DM Mono',monospace; font-size:0.58rem; color:#5878a8;
                letter-spacing:0.16em; margin-top:2px;">
      INTELLIGENT HEAT LOAD OPTIMISATION &nbsp;|&nbsp; NODE: {BACKEND_URL}
    </div>
  </div>
  <!-- status badges hidden for screen recording -->
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# MAIN DASHBOARD
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
    roi_inr  = result.get("annual_roi_inr", None)
    co2_kg   = result.get("co2_saved_hr_kg", None)

    # ── Alert banners ─────────────────────────────────────────
    # First pass: big dramatic banners for Corrosion & Mold
    if mode == "CORROSION_PREVENTION" or any("CORROSION" in w for w in warns):
        corrosion_msg = next((w for w in warns if "CORROSION" in w),
                             "Internal temperature near dew point — hull condensation risk is HIGH.")
        st.markdown(f"""
        <div class="warning-banner-corrosion">
          <div class="wb-inner">
            <div class="wb-icon">⚠️</div>
            <div>
              <div class="wb-title">🚨 Corrosion Risk — CRITICAL</div>
              <div class="wb-msg">{corrosion_msg}<br>
                Dew point proximity detected · Fans at 30% · Inspect hull panels immediately.
              </div>
            </div>
            <div class="wb-badge">HIGH RISK</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    if mode == "MOLD_ALERT" or any("MOLD" in w for w in warns):
        mold_msg = next((w for w in warns if "MOLD" in w),
                        "Humidity exceeded safe threshold — mold growth conditions detected.")
        st.markdown(f"""
        <div class="warning-banner-mold">
          <div class="wb-inner">
            <div class="wb-icon">⚠️</div>
            <div>
              <div class="wb-title">⚠ Mold Alert — Action Required</div>
              <div class="wb-msg">{mold_msg}<br>
                Dehumidification cycle active · Increase ventilation · Check cabin seals.
              </div>
            </div>
            <div class="wb-badge">WARNING</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # Second pass: smaller utility banners for other warn types
    for w in warns:
        if "CORROSION" in w or "MOLD" in w:
            continue  # already shown above as big banners
        if "HOSPITAL" in w or "MEDICINE" in w:
            st.markdown(f'<div class="alert-red">🏥 {w}</div>', unsafe_allow_html=True)
        elif "FAILSAFE" in w or "STALE" in w:
            st.markdown(f'<div class="alert-amber">📡 {w}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-red">⚠ {w}</div>', unsafe_allow_html=True)

    if is_heat:
        st.markdown('<div class="alert-blue">🌨️ HEATING MODE ACTIVE — Arctic/cold route detected.</div>',
                    unsafe_allow_html=True)

    # ── ■ ROI BANNER ─────────────────────────────────────────
    if roi_inr is not None:
        roi_str    = f"₹{roi_inr:,.0f}"
        co2_str    = f" &nbsp;·&nbsp; 🌿 CO₂ saved: {co2_kg} kg/hr" if co2_kg else ""
        saving_kwh = round(load_kw * savings / 100, 3)
        st.markdown(f"""
        <div class="roi-banner">
          <div class="roi-banner-icon">💰</div>
          <div>
            <div class="roi-banner-text">■ {roi_str} saved per year at this load level</div>
            <div class="roi-banner-sub">
              {load_kw:.3f} kW optimised &nbsp;·&nbsp; {savings:.1f}% reduction
              &nbsp;·&nbsp; {saving_kwh:.3f} kW freed vs full load{co2_str}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Top Metrics Row ───────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-box" style="border-top:3px solid #7a4fc0;">
          <div class="metric-lbl">Optimised Load</div>
          <div class="metric-val">{load_kw:.3f} <span style="font-size:0.9rem;">kW</span></div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-box" style="border-top:3px solid #1e80cc;">
          <div class="metric-lbl">HVAC Mode</div>
          <div class="metric-val" style="font-size:0.92rem; padding-top:6px; color:#1e80cc;">
            {mode.replace("_", " ")}
          </div>
        </div>""", unsafe_allow_html=True)
    with c3:
        roi_display = f"₹{roi_inr:,.0f}" if roi_inr is not None else "—"
        st.markdown(f"""
        <div class="metric-box" style="border-top:3px solid #20a868;">
          <div class="metric-lbl">Annual ROI</div>
          <div class="metric-val" style="color:#20a868;">{roi_display}</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        co2_display = f"{co2_kg} kg" if co2_kg is not None else "—"
        st.markdown(f"""
        <div class="metric-box" style="border-top:3px solid #18b098;">
          <div class="metric-lbl">CO₂ Saved / hr</div>
          <div class="metric-val" style="color:#18b098;">{co2_display}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Row 2: Load + Savings + Ship Status ──────────────────
    col_load, col_sav, col_status = st.columns([2, 1, 1])

    with col_load:
        num_class = "load-number heating" if is_heat else "load-number"
        box_class = "load-box heating-mode" if is_heat else "load-box"
        st.markdown(f"""
        <div class="{box_class}">
          <div class="section-label">// OPTIMISED HVAC LOAD</div>
          <div class="{num_class}">{load_kw:.3f}</div>
          <div class="load-unit">kilowatts</div>
          <div><span class="mode-badge mode-{mode}">{mode.replace("_", " ")}</span></div>
          <div style="margin-top:10px; font-family:'DM Mono',monospace; font-size:0.62rem;
                      color:#5878a8; letter-spacing:0.07em;">
            SETPOINT: {setpoint:.1f}°C &nbsp;·&nbsp; {cabin_id} &nbsp;·&nbsp;
            SRC: {wx_src.upper()} &nbsp;·&nbsp; SEG: {market.upper()} &nbsp;·&nbsp; {ship_length}m
          </div>
        </div>""", unsafe_allow_html=True)

    with col_sav:
        # Ghost Cooling triggers on MAINTENANCE_COOLING (mock/fixed engine) OR STANDBY (live engine)
        ghost_active = mode in ("MAINTENANCE_COOLING", "STANDBY")
        sav_border   = "#d08000" if ghost_active else ("#2a68e0" if is_heat else "#20a868")
        sav_color    = "#d08000" if ghost_active else ("#2a68e0" if is_heat else "#20a868")
        sav_bg       = "#fff9ed" if ghost_active else ("#eef2ff" if is_heat else "#edfdf5")
        sav_icon     = "⚙️" if ghost_active else ("🌨️" if is_heat else "⚡")
        sav_label    = "GHOST PROTOCOL" if ghost_active else ("HEATING MODE" if is_heat else "ENERGY SAVED")

        st.markdown(f"""
        <div class="savings-box" style="border-top-color:{sav_border};
             background:linear-gradient(145deg,#fff,{sav_bg});">
          <div class="section-label">// {sav_label}</div>
          <div class="savings-number" style="color:{sav_color};">{sav_icon} {savings:.1f}%</div>
          <div style="font-family:'DM Mono',monospace; font-size:0.64rem;
                      color:#5878a8; margin-top:5px;">vs full-load baseline</div>
        </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:7px'></div>", unsafe_allow_html=True)

        # Mode-specific sub-panel
        if mode in ("MAINTENANCE_COOLING", "STANDBY"):
            st.markdown(f"""
            <div style="background:#fffbf0; border:1.5px solid #f0d060;
                        border-left:4px solid #d08000; border-radius:9px; padding:10px;">
              <div style="font-family:'Nunito',sans-serif; font-size:0.70rem;
                          font-weight:800; color:#906000;">⚙️ GHOST COOLING ACTIVE</div>
              <div style="font-family:'DM Mono',monospace; font-size:0.68rem;
                          color:#385070; margin-top:4px;">
                Empty cabin · {100-savings:.0f}% load · {setpoint:.1f}°C setpoint
              </div>
            </div>""", unsafe_allow_html=True)
        elif mode == "CORROSION_PREVENTION":
            st.markdown("""
            <div style="background:#fff0f2; border:1.5px solid #f0a0b0;
                        border-left:4px solid #c83048; border-radius:9px; padding:10px;">
              <div style="font-family:'Nunito',sans-serif; font-size:0.70rem;
                          font-weight:800; color:#c83048;">🚨 CORROSION PREVENTION</div>
              <div style="font-family:'DM Mono',monospace; font-size:0.68rem;
                          color:#385070; margin-top:4px;">Fans 30% · Hull condensation risk</div>
            </div>""", unsafe_allow_html=True)
        elif mode == "MOLD_ALERT":
            st.markdown("""
            <div style="background:#fffbf0; border:1.5px solid #f0d060;
                        border-left:4px solid #d08000; border-radius:9px; padding:10px;">
              <div style="font-family:'Nunito',sans-serif; font-size:0.70rem;
                          font-weight:800; color:#906000;">⚠ MOLD ALERT</div>
              <div style="font-family:'DM Mono',monospace; font-size:0.68rem;
                          color:#385070; margin-top:4px;">Dehumidification · Ventilation ↑</div>
            </div>""", unsafe_allow_html=True)
        else:
            occ_color  = "#20a868" if occupancy else "#d08000"
            occ_bg     = "#edfdf5" if occupancy else "#fffbf0"
            occ_border = "#80d0a8" if occupancy else "#f0d060"
            occ_label  = "OCCUPIED — FULL COMFORT" if occupancy else "EMPTY — MONITORING"
            st.markdown(f"""
            <div style="background:{occ_bg}; border:1.5px solid {occ_border};
                        border-left:4px solid {occ_color}; border-radius:9px; padding:10px;">
              <div style="font-family:'Nunito',sans-serif; font-size:0.70rem;
                          font-weight:800; color:{occ_color};">
                {'✓' if occupancy else '○'} {occ_label}
              </div>
              <div style="font-family:'DM Mono',monospace; font-size:0.68rem;
                          color:#385070; margin-top:4px;">
                {occ_count} occupants · {setpoint:.1f}°C
              </div>
            </div>""", unsafe_allow_html=True)

    with col_status:
        st.markdown('<div class="section-label">// SHIP DYNAMICS</div>', unsafe_allow_html=True)
        for label, active, on_txt, off_txt, act_color, act_bg in [
            ("☀️ Direct Sun",  direct_sunlight,  "ACTIVE",   "NONE",   "#c83048", "#fff0f2"),
            ("🔥 Hull Soaked", heat_soaked_hull, "ACTIVE",   "NORMAL", "#c83048", "#fff0f2"),
            ("⚙️ Engine Adj",  engine_adjacent,  "ACTIVE",   "CLEAR",  "#f07050", "#fff8f5"),
            ("🧍 Occupancy",   occupancy,         "OCCUPIED", "EMPTY",  "#20a868", "#edfdf5"),
        ]:
            txt   = on_txt if active else off_txt
            color = act_color if active else "#5878a8"
            bg    = act_bg   if active else "#f2f6fc"
            st.markdown(f"""
            <div class="status-row" style="background:{bg};">
              <span class="label-muted">{label}</span>
              <span style="color:{color}; font-weight:700; font-size:0.72rem;">{txt}</span>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:5px'></div>", unsafe_allow_html=True)

        if dew_pt is not None:
            margin   = internal_temp - dew_pt
            dp_color = "#c83048" if margin < 1.0 else ("#d08000" if margin < 3.0 else "#20a868")
            st.markdown(f"""
            <div class="status-row">
              <span class="label-muted">💧 Dew Pt</span>
              <span style="color:{dp_color}; font-weight:700;">{dew_pt:.1f}°C</span>
            </div>
            <div class="status-row">
              <span class="label-muted">📏 Margin</span>
              <span style="color:{dp_color}; font-weight:700;">{margin:.1f}°C</span>
            </div>""", unsafe_allow_html=True)

        ext_disp = f"{external_temp:.1f}°C" if manual_weather and external_temp else "AUTO"
        for lbl, val in [
            ("🌡️ Ext",   ext_disp),
            ("💧 RH",    f"{internal_rh:.0f}%"),
            ("🏢 Seg",   market.upper()),
            ("🚢 Ship",  f"{ship_length}m"),
            ("🪟 Win",   f"{window_area:.1f}m²"),
            ("🔌 Equip", f"{equip_watts}W"),
        ]:
            st.markdown(f"""
            <div class="status-row">
              <span class="label-muted">{lbl}</span>
              <span style="color:#1e80cc; font-weight:700;">{val}</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Row 3: AI Decision Log + 11-Bar Heat Breakdown ────────
    col_log, col_chart = st.columns([3, 2])

    with col_log:
        st.markdown('<div class="section-label">// AI DECISION LOG — REASONING TRACE</div>',
                    unsafe_allow_html=True)
        log_lines = result.get("decision_log", ["No log available."])
        log_html  = colorise_log(log_lines)
        ts        = time.strftime("%H:%M:%S")
        st.markdown(f"""
        <div class="decision-log">
<span class="log-header">MAR-HVAC ENGINE — {ts} — {cabin_id}</span>

{log_html}
        </div>""", unsafe_allow_html=True)

        # ── MAR-Chat ─────────────────────────────────────────
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="section-label">// MAR-CHAT — ASK THE AI</div>',
                    unsafe_allow_html=True)
        chat_col1, chat_col2 = st.columns([5, 1])
        with chat_col1:
            chat_q = st.text_input(
                "Ask a question about this HVAC decision",
                placeholder="e.g. Why is this mode active? How much am I saving?",
                label_visibility="collapsed",
            )
        with chat_col2:
            chat_btn = st.button("Ask →", use_container_width=True)

        if chat_btn and chat_q.strip():
            st.session_state["chat_response"] = ask_mar_chat_local(chat_q, result)

        if st.session_state["chat_response"]:
            st.markdown(f"""
            <div class="mar-chat-box">🤖 {st.session_state["chat_response"]}</div>
            """, unsafe_allow_html=True)

    with col_chart:
        st.markdown('<div class="section-label">// HEAT LOAD BREAKDOWN — 11 VARIABLES (kW)</div>',
                    unsafe_allow_html=True)
        bd = result.get("breakdown", {})
        labels = [
            "Wall Transmission", "Solar (Porthole)",    "Fenestration (Windows)",
            "Metabolic (People)", "Equipment",           "Engine Radiant",
            "Thermal Lag",        "Ceiling (Solar-Air)", "Floor Conduction",
            "Latent (Salt Air)",  "Heating Load",
        ]
        values = [
            bd.get("q_transmission", 0),  bd.get("q_solar", 0),        bd.get("q_fenestration", 0),
            bd.get("q_metabolic", 0),     bd.get("q_equipment", 0),    bd.get("q_engine_radiant", 0),
            bd.get("q_thermal_lag", 0),   bd.get("q_ceiling", 0),      bd.get("q_floor_conduction", 0),
            bd.get("q_latent", 0),        bd.get("heating_load_kw", 0),
        ]
        bar_colors = [
            "#6ab8e8", "#f8c820", "#7a4fc0", "#6ed8b0", "#9880d8",
            "#f07050", "#f8a888", "#f8c820", "#6ed8b0", "#9880d8", "#6ab8e8",
        ]
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation="h",
            marker=dict(color=bar_colors, line=dict(color="#c8d8f0", width=1)),
            text=[f"{v:.3f}" for v in values],
            textposition="outside",
            textfont=dict(family="DM Mono", size=8, color="#385070"),
        ))
        fig.add_vline(
            x=load_kw, line_dash="dash", line_color="#7a4fc0", line_width=1.5,
            annotation_text=f"Opt: {load_kw:.3f}kW",
            annotation_font=dict(color="#7a4fc0", size=8, family="DM Mono"),
            annotation_position="top right",
        )
        fig.update_layout(
            paper_bgcolor="#ffffff", plot_bgcolor="#f2f6fc",
            font=dict(family="DM Mono", size=8, color="#5878a8"),
            margin=dict(l=10, r=65, t=8, b=16), height=340,
            xaxis=dict(gridcolor="#dce8f5", zeroline=True, zerolinecolor="#c8d8f0"),
            yaxis=dict(gridcolor="#dce8f5"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Row 4: Asset Defence Gauges + 14-Day Forecast ────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    col_gauge, col_fc = st.columns([1, 2])

    with col_gauge:
        st.markdown('<div class="section-label">// ASSET DEFENCE GAUGES</div>',
                    unsafe_allow_html=True)

        # Dew point gauge
        if dew_pt is not None:
            fig_dew = go.Figure(go.Indicator(
                mode="gauge+number+delta", value=internal_temp,
                delta={"reference": dew_pt,
                       "increasing": {"color": "#20a868"},
                       "decreasing": {"color": "#c83048"}},
                title={"text": "Temp vs Dew Point (°C)",
                       "font": {"family": "Nunito", "size": 10, "color": "#5878a8"}},
                number={"font": {"family": "DM Mono", "size": 24, "color": "#7a4fc0"}, "suffix": "°C"},
                gauge={
                    "axis": {"range": [dew_pt - 5, internal_temp + 10], "tickcolor": "#5878a8"},
                    "bar": {"color": "#9880d8"},
                    "bgcolor": "#f2f6fc", "bordercolor": "#c8d8f0",
                    "steps": [
                        {"range": [dew_pt - 5, dew_pt + 1], "color": "rgba(200,48,72,0.18)"},
                        {"range": [dew_pt + 1, dew_pt + 3], "color": "rgba(208,128,0,0.15)"},
                        {"range": [dew_pt + 3, internal_temp + 10], "color": "rgba(32,168,104,0.12)"},
                    ],
                    "threshold": {"line": {"color": "#c83048", "width": 2},
                                  "thickness": 0.8, "value": dew_pt + 1},
                },
            ))
            fig_dew.update_layout(
                paper_bgcolor="#ffffff", font_color="#5878a8",
                margin=dict(l=16, r=16, t=36, b=8), height=188,
            )
            st.plotly_chart(fig_dew, use_container_width=True, config={"displayModeBar": False})

        # Humidity / mold gauge
        mold_thresh = {"cargo": 70, "cruise": 65, "navy": 60, "hospital": 55, "yacht": 60}.get(market, 70)
        fig_rh = go.Figure(go.Indicator(
            mode="gauge+number", value=internal_rh,
            title={"text": f"Humidity % (mold >{mold_thresh}%)",
                   "font": {"family": "Nunito", "size": 10, "color": "#5878a8"}},
            number={"font": {"family": "DM Mono", "size": 24, "color": "#18b098"}, "suffix": "%"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#6ed8b0"},
                "bgcolor": "#f2f6fc", "bordercolor": "#c8d8f0",
                "steps": [
                    {"range": [0, mold_thresh], "color": "rgba(32,168,104,0.12)"},
                    {"range": [mold_thresh, 100], "color": "rgba(208,128,0,0.15)"},
                ],
                "threshold": {"line": {"color": "#d08000", "width": 2},
                              "thickness": 0.8, "value": mold_thresh},
            },
        ))
        fig_rh.update_layout(
            paper_bgcolor="#ffffff", font_color="#5878a8",
            margin=dict(l=16, r=16, t=36, b=8), height=168,
        )
        st.plotly_chart(fig_rh, use_container_width=True, config={"displayModeBar": False})

    with col_fc:
        st.markdown('<div class="section-label">// 14-DAY ANTICIPATORY COOLING FORECAST</div>',
                    unsafe_allow_html=True)
        if st.button("📡 Load Forecast Chart", use_container_width=False):
            st.session_state["forecast_points"] = api_forecast()

        pts = st.session_state.get("forecast_points", [])
        if pts:
            df = pd.DataFrame(pts)
            df["Time"] = pd.to_datetime(df["ts"], unit="s")
            fig_fc = go.Figure()
            fig_fc.add_trace(go.Scatter(
                x=df["Time"], y=df["temp"], mode="lines+markers", name="Temp °C",
                line=dict(color="#1e80cc", width=2.5),
                marker=dict(color="#7a4fc0", size=4),
                fill="tozeroy", fillcolor="rgba(122,79,192,0.08)",
            ))
            if "humidity" in df.columns:
                fig_fc.add_trace(go.Scatter(
                    x=df["Time"], y=df["humidity"], mode="lines", name="Humidity %",
                    line=dict(color="#9880d8", width=2, dash="dot"), yaxis="y2",
                ))
            fig_fc.add_hline(
                y=target_temp, line_dash="dot", line_color="#20a868",
                annotation_text=f"Setpoint {target_temp:.1f}°C",
                annotation_font=dict(color="#20a868", size=8, family="DM Mono"),
            )
            fig_fc.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#f2f6fc",
                font=dict(family="DM Mono", size=8, color="#5878a8"),
                margin=dict(l=10, r=55, t=8, b=28), height=320,
                xaxis=dict(gridcolor="#dce8f5", tickangle=-40),
                yaxis=dict(title="Temp (°C)", gridcolor="#dce8f5"),
                yaxis2=dict(title="Humidity (%)", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                            font=dict(family="DM Mono", size=8)),
            )
            st.plotly_chart(fig_fc, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("""
            <div style="background:#f2f6fc; border:1.5px solid #c8d8f0; border-radius:10px;
                        padding:36px; text-align:center; color:#5878a8;
                        font-family:'DM Mono',monospace; font-size:0.76rem; line-height:1.8;">
              Press '📡 Load Forecast Chart' to display the 14-day route forecast.<br><br>
              First fetch the buffer via the 🔄 FORECAST button in the sidebar.
            </div>""", unsafe_allow_html=True)

else:
    # ── Idle / ready state ────────────────────────────────────
    st.markdown("""
    <div style="text-align:center; padding:70px 40px; background:#ffffff;
                border:1.5px solid #c8d8f0; border-radius:14px;
                box-shadow:0 4px 20px rgba(122,79,192,0.10);">
      <div style="font-size:3.5rem; margin-bottom:14px;">🚢</div>
      <div style="font-family:'Nunito',sans-serif; font-weight:900; font-size:1.2rem;
                  color:#7a4fc0; letter-spacing:0.04em;">MAR-HVAC AI READY</div>
      <div style="margin-top:8px; font-family:'DM Mono',monospace; font-size:0.75rem;
                  color:#5878a8; line-height:1.8;">
        Configure cabin parameters in the sidebar and press ⚡ CALCULATE
      </div>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────

st.markdown("""
<div style="margin-top:20px; text-align:center; font-family:'DM Mono',monospace;
            font-size:0.55rem; color:#9880d8;
            border-top:1.5px solid #c8d8f0; padding-top:10px;">
  MAR-HVAC AI v2.0 &nbsp;·&nbsp; Merged Final &nbsp;·&nbsp; ASHRAE + IMO 2030
  &nbsp;·&nbsp; AutoCAD Parser · MAR-Chat · ROI Banner · Asset Defence · 14-Day Forecast
  &nbsp;·&nbsp; Government Polytechnic Pune — Idea Forge 2026
</div>
""", unsafe_allow_html=True)