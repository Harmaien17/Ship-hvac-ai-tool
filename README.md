\# 🚢 MAR-HVAC AI 

\*\*Edge-Distributed HVAC Optimization \& Thermodynamic Engine for Maritime Vessels\*\* \*Idea Forge 2026 Submission | Government Polytechnic Pune\*



\---



\## 🌊 Overview

MAR-HVAC AI is a decentralized, Edge-AI cooling optimization system designed specifically for deep-sea cargo ships. By calculating an 11-variable thermodynamic matrix in real-time, the system reduces compressor load, cuts marine diesel CO2 emissions, and saves vessel owners approximately \*\*₹12,00,000 to ₹18,00,000 annually\*\*. 



Built for deep-sea resilience, the architecture operates fully autonomously even during Starlink/Satellite connectivity dropouts.



\---



\## ✨ Core Features



\### 🧠 The "Brain": 11-Variable Thermodynamic Engine (Backend)

\* \*\*Precision Load Math:\*\* Dynamically calculates cooling requirements (kW) by factoring in U-values of the hull, solar heat gain (SHGC), engine room radiant heat, thermal lag, latent heat, and metabolic/equipment loads.

\* \*\*Deep-Sea Resilience (Failsafe):\*\* Constantly monitors Starlink satellite connectivity. If internet drops, the system seamlessly falls back to a locally generated \*\*14-day weather cache\*\* (`forecast\_cache.json`) to maintain anticipatory cooling.

\* \*\*Economic ROI Tracker:\*\* Translates energy savings directly into Indian Rupees (₹) and tracks live CO2 reduction (using the 0.68 kg/kWh marine diesel emission factor).

\* \*\*Waste Heat Offset:\*\* Includes an endpoint to calculate potential HVAC compressor offsets using engine exhaust waste heat recovery.



\### 🖥️ The Command Center (Frontend)

\* \*\*Local AutoCAD Parsing:\*\* An Edge-computed PDF parser that extracts cabin dimensions (m²) directly from ship blueprints without sending heavy files over expensive satellite internet.

\* \*\*Anticipatory Cooling Charts:\*\* Interactive Plotly charts mapping the 14-day temperature and humidity forecasts to prepare the cabin environment ahead of weather fronts.

\* \*\*Live "Chatbot" Decision Log:\*\* Real-time, human-readable explanations of the AI's thermodynamic choices (e.g., \*“Occupancy Sensor: Empty. Triggering STANDBY mode.”\*).



\---



\## 🛠️ Tech Stack

\* \*\*Backend:\*\* Python 3.12, FastAPI, Pydantic, Uvicorn

\* \*\*Frontend:\*\* Streamlit, Plotly, Pandas, PyPDF

\* \*\*External Integrations:\*\* OpenWeather API (simulating Starlink feed)

\* \*\*Architecture:\*\* Distributed Edge-Compute (Designed to run on low-RAM shipboard IoT nodes).



\---



\## 🚀 How to Run Locally



\### 1. Start the AI Engine (Backend)

Open a terminal in the root directory and start the FastAPI server:

```bash

python -m uvicorn backend.main:app --reload

