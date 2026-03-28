"""
MAR-HVAC AI — AutoCAD Drawing Parser + MAR-Chat
backend/autocad_parser.py  +  backend/mar_chat.py

WEEK 6 — Both modules in one file for simplicity.
Split into separate files when ready.

autocad_parser:
  - Accepts a PDF ship drawing (uploaded via /api/v1/parse-drawing)
  - Extracts: room name, dimensions (LxWxH), material, cabin area, window area
  - Auto-fills CabinTelemetry fields → no manual entry needed
  - Uses pypdf for text extraction + regex for dimension parsing

mar_chat:
  - Engineers type natural language questions about their HVAC system
  - AI reads the last HVACDecision and explains it in plain English
  - Uses OpenAI or Anthropic API (Claude) depending on what key is in .env
  - Example: "Why is CABIN-A3 running at full cooling?"

YOU are the only one who edits this file.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional
from io import BytesIO

logger = logging.getLogger("mar_hvac.week6")


# ─────────────────────────────────────────────────────────────
# SECTION 1 — AUTOCAD PARSER
# ─────────────────────────────────────────────────────────────

def parse_ship_drawing_pdf(pdf_bytes: bytes, cabin_hint: str = "") -> dict:
    """
    Parse a ship drawing PDF and extract cabin geometry data.

    Returns a dict that maps directly to CabinTelemetry fields:
      {
        "success": True/False,
        "cabin_id": "...",
        "cabin_area_m2": float,
        "window_area_m2": float,
        "ceiling_height_m": float,
        "wall_material": "...",
        "u_value_override": float or None,
        "raw_text_snippet": "...",
        "parse_notes": [...]
      }

    How to call this from main.py:
      result = parse_ship_drawing_pdf(await file.read(), cabin_hint="A3")
    """
    notes = []

    # Try to import pypdf — graceful failure if not installed
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("[PARSER] pypdf not installed. Run: pip install pypdf")
        return {
            "success": False,
            "parse_notes": ["pypdf not installed. Run: pip install pypdf"],
            "raw_text_snippet": "",
        }

    # Read all text from the PDF
    try:
        reader     = PdfReader(BytesIO(pdf_bytes))
        full_text  = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
        full_text = full_text.strip()
        logger.info(f"[PARSER] Extracted {len(full_text)} chars from {len(reader.pages)} pages.")
    except Exception as e:
        logger.error(f"[PARSER] PDF read error: {e}")
        return {"success": False, "parse_notes": [f"PDF read error: {e}"], "raw_text_snippet": ""}

    if not full_text:
        return {"success": False, "parse_notes": ["No text found — PDF may be a scanned image."], "raw_text_snippet": ""}

    result = {
        "success"         : False,
        "cabin_id"        : "PARSED-CABIN",
        "cabin_area_m2"   : None,
        "window_area_m2"  : None,
        "ceiling_height_m": None,
        "wall_material"   : None,
        "u_value_override": None,
        "raw_text_snippet": full_text[:500],
        "parse_notes"     : notes,
    }

    # ── Extract cabin/room ID ─────────────────────────────────
    # Patterns like "CABIN A3", "ROOM B-04", "STATEROOM 12"
    cabin_patterns = [
        r"(?:CABIN|ROOM|STATEROOM|COMPARTMENT)\s+([A-Z0-9\-]+)",
        r"([A-Z]{1,3}\-?\d{1,3})\s+(?:CABIN|ROOM|STATEROOM)",
    ]
    for pat in cabin_patterns:
        m = re.search(pat, full_text.upper())
        if m:
            result["cabin_id"] = f"CABIN-{m.group(1).strip()}"
            notes.append(f"Cabin ID extracted: {result['cabin_id']}")
            break
    if cabin_hint:
        result["cabin_id"] = f"CABIN-{cabin_hint.upper()}"

    # ── Extract dimensions ────────────────────────────────────
    # Common drawing notations:
    #   "4.5 x 3.2 m"  |  "4500 x 3200 mm"  |  "L=4.5 W=3.2 H=2.4"
    #   "4.5m x 3.2m"  |  "4.5 × 3.2"

    # Pattern 1: decimal metres — "4.5 x 3.2" or "4.5 × 3.2"
    m_met = re.search(
        r"(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)\s*(?:m|M|metre|meter)?",
        full_text
    )
    # Pattern 2: millimetres — "4500 x 3200 mm"
    m_mm = re.search(
        r"(\d{3,5})\s*[xX×]\s*(\d{3,5})\s*(?:mm|MM|millimeter|millimetre)",
        full_text
    )
    # Pattern 3: explicit L x W notation
    m_lw = re.search(
        r"L\s*[=:]\s*(\d+\.?\d*)\s*.*?W\s*[=:]\s*(\d+\.?\d*)",
        full_text, re.IGNORECASE
    )

    length_m = width_m = None

    if m_lw:
        length_m = float(m_lw.group(1))
        width_m  = float(m_lw.group(2))
        notes.append(f"Dimensions from L/W notation: {length_m}m x {width_m}m")
    elif m_mm:
        length_m = float(m_mm.group(1)) / 1000.0
        width_m  = float(m_mm.group(2)) / 1000.0
        notes.append(f"Dimensions from mm: {length_m}m x {width_m}m")
    elif m_met:
        v1 = float(m_met.group(1))
        v2 = float(m_met.group(2))
        # Sanity check: cabin dimensions should be 2-20m
        if 2.0 <= v1 <= 20.0 and 2.0 <= v2 <= 20.0:
            length_m = v1
            width_m  = v2
            notes.append(f"Dimensions from metres: {length_m}m x {width_m}m")
        else:
            notes.append(f"Found {v1} x {v2} but values seem non-physical — skipping.")

    if length_m and width_m:
        result["cabin_area_m2"] = round(length_m * width_m, 2)
        notes.append(f"Cabin area: {result['cabin_area_m2']} m2")
        result["success"] = True
    else:
        notes.append("Could not extract dimensions — try a cleaner drawing.")

    # ── Extract ceiling height ────────────────────────────────
    m_h = re.search(
        r"(?:H|HEIGHT|CEILING|CLEAR)\s*[=:\s]\s*(\d+\.?\d*)\s*(?:m|M|mm|MM)?",
        full_text, re.IGNORECASE
    )
    if m_h:
        h_val = float(m_h.group(1))
        if h_val > 10:        # probably mm
            h_val = h_val / 1000.0
        if 1.8 <= h_val <= 5.0:
            result["ceiling_height_m"] = round(h_val, 2)
            notes.append(f"Ceiling height: {result['ceiling_height_m']}m")

    # ── Extract window/porthole area ──────────────────────────
    m_win = re.search(
        r"(?:WINDOW|PORTHOLE|GLAZING)\s+(?:AREA\s+)?[=:\s]?\s*(\d+\.?\d*)\s*(?:m2|M2|SQM)?",
        full_text, re.IGNORECASE
    )
    if m_win:
        w_area = float(m_win.group(1))
        if w_area > 50:    # probably cm2 or mm2 — convert
            w_area = w_area / 10000.0
        if 0.01 <= w_area <= 10.0:
            result["window_area_m2"] = round(w_area, 3)
            notes.append(f"Window area: {result['window_area_m2']} m2")

    # ── Detect material ───────────────────────────────────────
    material_keywords = {
        "steel":     ("steel",    2.5),
        "aluminum":  ("aluminum", 1.8),
        "aluminium": ("aluminium",1.8),
        "composite": ("composite",0.8),
        "insulated": ("insulated",0.65),
        "mineral":   ("mineral wool", 0.55),
        "foam":      ("foam insulation", 0.45),
    }
    full_upper = full_text.upper()
    for keyword, (label, u_val) in material_keywords.items():
        if keyword.upper() in full_upper:
            result["wall_material"]   = label
            result["u_value_override"] = u_val
            notes.append(f"Material detected: {label} (U = {u_val} W/m2K)")
            break

    if not result["wall_material"]:
        notes.append("Material not detected — using default U = 0.65 W/m2K (insulated).")

    logger.info(f"[PARSER] Result: area={result['cabin_area_m2']}m2 | "
                f"window={result['window_area_m2']}m2 | "
                f"material={result['wall_material']}")
    return result


# ─────────────────────────────────────────────────────────────
# SECTION 2 — MAR-CHAT
# ─────────────────────────────────────────────────────────────

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY",     "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _build_hvac_context(last_decision: Optional[dict]) -> str:
    """Convert the last HVACDecision JSON into a readable context string for the AI."""
    if not last_decision:
        return "No recent HVAC calculation available. Ask the engineer to run a cabin optimisation first."

    ctx_lines = [
        f"Cabin ID: {last_decision.get('cabin_id', 'N/A')}",
        f"Mode: {last_decision.get('mode', 'N/A')}",
        f"Optimised Load: {last_decision.get('optimized_load_kw', 'N/A')} kW",
        f"Setpoint: {last_decision.get('setpoint_actual', 'N/A')}°C",
        f"Energy Saved: {last_decision.get('energy_saved_percent', 'N/A')}%",
        f"Weather Source: {last_decision.get('weather_source', 'N/A')}",
        f"Dew Point: {last_decision.get('dew_point', 'N/A')}°C",
        f"Warnings: {last_decision.get('warnings', [])}",
    ]
    bd = last_decision.get("breakdown", {})
    if bd:
        ctx_lines.append("Heat Load Breakdown (kW):")
        for key, val in bd.items():
            ctx_lines.append(f"  {key}: {val}")
    return "\n".join(ctx_lines)


def ask_mar_chat(
    question       : str,
    last_decision  : Optional[dict] = None,
    cabin_id       : str            = "",
) -> str:
    """
    Ask MAR-Chat a natural language question about the HVAC system.

    Tries Anthropic Claude first, then OpenAI GPT-4o as fallback.
    Returns the AI response as a string.
    If no API keys are set, returns a rule-based response.

    Args:
      question      : Engineer's question in plain English
      last_decision : The last HVACDecision as a dict (from /optimize response)
      cabin_id      : Optional cabin context

    Returns:
      str — AI explanation
    """

    hvac_context = _build_hvac_context(last_decision)
    cabin_ref    = f" for cabin {cabin_id}" if cabin_id else ""

    system_prompt = (
        "You are MAR-HVAC AI Assistant — an expert marine HVAC engineer AI. "
        "You explain HVAC decisions in clear, professional language to ship engineers. "
        "You reference specific numbers from the provided HVAC data. "
        "Keep answers concise (3-5 sentences). Use maritime terminology. "
        "If asked why the system chose a specific mode, explain the exact conditions that triggered it."
    )

    user_message = (
        f"HVAC System Data{cabin_ref}:\n"
        f"{'='*40}\n"
        f"{hvac_context}\n"
        f"{'='*40}\n\n"
        f"Engineer's Question: {question}"
    )

    # ── Try Anthropic Claude ──────────────────────────────────
    if ANTHROPIC_API_KEY:
        try:
            import requests
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-3-haiku-20240307",   # fast + cheap
                    "max_tokens": 400,
                    "system":     system_prompt,
                    "messages":   [{"role": "user", "content": user_message}],
                },
                timeout=15,
            )
            resp.raise_for_status()
            content = resp.json().get("content", [])
            if content:
                return content[0].get("text", "No response from Claude.")
        except Exception as e:
            logger.warning(f"[MAR-CHAT] Claude API failed: {e}. Trying OpenAI...")

    # ── Try OpenAI GPT ────────────────────────────────────────
    if OPENAI_API_KEY:
        try:
            import requests
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":      "gpt-4o-mini",
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system",  "content": system_prompt},
                        {"role": "user",    "content": user_message},
                    ],
                },
                timeout=15,
            )
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if choices:
                return choices[0]["message"]["content"]
        except Exception as e:
            logger.warning(f"[MAR-CHAT] OpenAI API failed: {e}. Using rule-based fallback.")

    # ── Rule-based fallback (no API keys needed) ──────────────
    return _rule_based_response(question, last_decision)


def _rule_based_response(question: str, last_decision: Optional[dict]) -> str:
    """
    Simple keyword-based HVAC response when no AI API key is available.
    Good enough for demo purposes.
    """
    if not last_decision:
        return (
            "No HVAC data available yet. Please run a cabin optimisation "
            "using the ⚡ CALCULATE button first, then ask your question."
        )

    q_lower  = question.lower()
    mode     = last_decision.get("mode", "UNKNOWN")
    load_kw  = last_decision.get("optimized_load_kw", 0)
    savings  = last_decision.get("energy_saved_percent", 0)
    dew_pt   = last_decision.get("dew_point", 0)
    warnings = last_decision.get("warnings", [])
    cabin_id = last_decision.get("cabin_id", "the cabin")

    if any(w in q_lower for w in ["why", "reason", "cause", "trigger"]):
        if mode == "MAINTENANCE_COOLING":
            return (
                f"{cabin_id} is in Ghost Cooling mode because the PIR occupancy sensor "
                f"reports the cabin is empty. The system has reduced load to "
                f"{100-savings:.0f}% of full capacity, saving {savings:.0f}% energy "
                f"while maintaining a relaxed setpoint to prevent mold and corrosion."
            )
        elif mode == "CORROSION_PREVENTION":
            return (
                f"{cabin_id} triggered Corrosion Prevention because internal temperature "
                f"is dangerously close to the dew point ({dew_pt:.1f}°C). "
                f"Condensation on steel hull leads to accelerated corrosion. "
                f"Fans are running at 30% to circulate air and keep surfaces dry."
            )
        elif mode == "MOLD_ALERT":
            return (
                f"{cabin_id} is in Mold Alert because humidity has exceeded the safe "
                f"threshold for this vessel type and the cabin is unoccupied. "
                f"Sustained high humidity in an empty cabin creates ideal mold growth conditions. "
                f"The dehumidification cycle is now active."
            )
        elif mode == "EMERGENCY_HEAT":
            return (
                f"{cabin_id} has switched to heating mode because external temperature "
                f"has dropped below the target setpoint — this typically indicates "
                f"an arctic or cold-weather route. The system is supplying heat to "
                f"maintain crew comfort."
            )
        elif mode == "FULL_COOLING":
            return (
                f"{cabin_id} is running at full cooling because the calculated heat load "
                f"is near the cabin's maximum thermal capacity. Contributing factors include "
                f"high external temperature, direct solar gain, occupant metabolic heat, "
                f"and equipment load. All are accounted for in the breakdown."
            )
    if any(w in q_lower for w in ["save", "saving", "efficient", "energy"]):
        return (
            f"The system is saving {savings:.1f}% energy versus running at full load. "
            f"The optimised load is {load_kw:.3f} kW. "
            f"Ghost Cooling Protocol is the primary energy-saving mechanism for empty cabins, "
            f"reducing load to 40-50% of baseline."
        )
    if any(w in q_lower for w in ["safe", "ok", "normal", "fine"]):
        if warnings:
            return f"Attention required: {warnings[0]}"
        return (
            f"{cabin_id} is operating normally in {mode.replace('_', ' ')} mode "
            f"at {load_kw:.3f} kW. No warnings active. All sensor readings are within safe limits."
        )

    return (
        f"{cabin_id} is currently in {mode.replace('_', ' ')} mode at {load_kw:.3f} kW "
        f"({savings:.0f}% energy saved). "
        f"Ask me why the mode was chosen, about energy savings, or about any warnings."
    )