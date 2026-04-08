# 🚢 MAR-HVAC AI 
**Edge-Distributed HVAC Optimization & Thermodynamic Engine for Maritime Vessels** *Idea Forge 2026 Submission | Government Polytechnic Pune*

---

## 🌊 Executive Summary
MAR-HVAC AI is a decentralized, Edge-AI cooling optimization system engineered specifically for deep-sea commercial vessels. By computing an 11-variable thermodynamic matrix in real-time, the system autonomously minimizes compressor load, significantly reduces marine diesel CO₂ emissions, and delivers an estimated **₹12,00,000 to ₹18,00,000 in annual operational savings** per vessel. 

Designed with deep-sea resilience at its core, the architecture operates fully autonomously on low-RAM edge nodes. Moving beyond simple fuel savings, the system acts as a dedicated **ESG Monetization Engine**, actively generating carbon credits and ensuring compliance with strict global maritime emission regulations (IMO 2030) even during prolonged Starlink or satellite connectivity blackouts.

---

## ✨ Core Architecture & Features

### 🧠 The "Brain": 11-Variable Thermodynamic Engine (Backend)
* **Dynamic 11-Point Load Modeling:** Precisely calculates cooling requirements (kW) by synthesizing hull U-values, thermal lag, latent heat extraction, engine room radiant heat, and metabolic/equipment loads.
* **Dynamic Solar & Geometry Scaling:** Incorporates adjustable window configurations to accurately scale the Solar Heat Gain Coefficient (SHGC), seamlessly adapting calculations for diverse vessel layouts—from standard crew cabins to multi-window bridge decks.
* **Deep-Sea Failsafe Resilience:** Continuously monitors satellite connectivity. In the event of an internet blackout, the system seamlessly transitions to a locally generated **14-day weather cache** (`forecast_cache.json`) to sustain anticipatory cooling without disruption.
* **Real-Time Economic & Carbon Tracking:** Translates energy optimizations directly into Indian Rupees (₹) and tracks active CO₂ reductions utilizing the standard 0.68 kg/kWh marine diesel emission factor.
* **Waste Heat Offset Analysis:** Features an integrated endpoint to calculate potential HVAC compressor offsets by recovering energy from engine exhaust waste heat.

### 🖥️ The Command Center (Frontend Edge Dashboard)
* **💼 Dual-Persona UI Architecture:** Dynamically adapts the dashboard interface based on the stakeholder:
  * **Chief Engineer View:** Displays raw thermodynamic telemetry, live asset defense gauges (dew point/mold risk), and autonomous decision logs.
  * **Fleet CFO View:** Abstracts the physics to deliver a high-level executive summary focusing purely on total financial impact, ROI calculation matrices, and carbon market valuations.
* **🌿 ESG & Carbon Credit Monetization:** Translates mitigated CO₂ emissions into verified Carbon Credits. Automatically calculates the open-market trading value (e.g., ₹4,000 / $50 USD per tonne) of saved energy, transforming the HVAC system from a cost-saver into a revenue-generator.
* **⚖️ IMO 2030 Regulatory Compliance:** Directly tracks metrics to improve the vessel's **Carbon Intensity Indicator (CII)** rating, preventing heavy regulatory fines and protecting fleets from forced slow-steaming penalties.
* **📐 Edge AutoCAD Parsing:** An edge-computed PDF/DWG parser that autonomously extracts cabin geometry (m²) directly from ship blueprints, eliminating the need to transmit heavy CAD files over limited Starlink bandwidth.
* **📡 Anticipatory Cooling & Live Telemetry:** Interactive Plotly visualizations map 14-day temperature and humidity forecasts, while a live dashboard badge monitors real-time Starlink/Edge connectivity status.
* **⚙️ Autonomous Decision Logging:** Provides a real-time, human-readable audit trail of the AI's thermodynamic adjustments (e.g., *“Occupancy Sensor: Empty. Triggering STANDBY mode.”*).

---

## 🛠️ Technical Stack
* **Backend Engine:** Python 3.12, FastAPI, Pydantic, Uvicorn
* **Frontend Dashboard:** Streamlit, Plotly, Pandas, PyPDF
* **External Integrations:** OpenWeather API (simulating live Starlink telemetry)
* **Architecture:** Distributed Edge-Compute (Optimized for low-RAM shipboard IoT deployment)

---

## 🚀 Deployment Instructions

### 1. Initialize the AI Engine (Backend)
Open a terminal in the root directory, activate your virtual environment, and start the FastAPI server:
```bash
python -m uvicorn backend.main:app --reload


### 2. Launch the Command Center (Frontend)
Open a second terminal, ensure the virtual environment is active, and boot the Streamlit dashboard:
```bash
cd frontend
streamlit run app.py
