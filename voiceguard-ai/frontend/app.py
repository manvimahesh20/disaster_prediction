import os
import time
import requests
from datetime import datetime
import streamlit as st


st.set_page_config(page_title="VoiceGuard AI — Console", layout="wide")

st.title("VoiceGuard AI — Operations Console")

# ---------- Mock data (copied from the React app) ----------
MOCK_ALERTS = [
    {"id": "a1", "timestamp": "14:42:09", "disaster_type": "Coastal Flood", "location": "Mangaluru / Panambur", "severity": "HIGH", "source": "auto", "posts": 184},
    {"id": "a2", "timestamp": "14:31:55", "disaster_type": "Heavy Rainfall", "location": "Udupi / Malpe", "severity": "MEDIUM", "source": "voice", "posts": 67},
    {"id": "a3", "timestamp": "14:18:20", "disaster_type": "Storm Surge", "location": "Karwar / Devbagh", "severity": "MEDIUM", "source": "auto", "posts": 41},
    {"id": "a4", "timestamp": "13:54:02", "disaster_type": "Landslide Risk", "location": "Kundapura / Maravanthe", "severity": "LOW", "source": "manual", "posts": 12},
    {"id": "a5", "timestamp": "13:22:48", "disaster_type": "High Tide Warning", "location": "Bhatkal", "severity": "LOW", "source": "auto", "posts": 8},
]

TICKER = [
    "IMD COASTAL BULLETIN — RED ALERT DAKSHINA KANNADA",
    "SDRF DEPLOYED · PANAMBUR FISHING HARBOUR",
    "184 POSTS PROCESSED IN LAST 60s",
    "VOICE AGENT LIVE · KAN / ENG / TUL",
    "TIDE +1.8m · STORM SURGE PROBABILITY 0.71",
    "EVACUATION ROUTE NH-66 NORTHBOUND CLEAR",
]

SEV_TOKEN = {
    "LOW":   {"label": "NOMINAL"},
    "MEDIUM": {"label": "ELEVATED"},
    "HIGH":  {"label": "CRITICAL"},
}

SOURCE_LABEL = {"auto": "AUTO·SCAN", "voice": "VOICE·IN", "manual": "OPERATOR"}


def probe_backend(url: str):
    try:
        r = requests.get(url, timeout=1.5)
        return r.ok
    except Exception:
        return False


if "alerts" not in st.session_state:
    st.session_state.alerts = MOCK_ALERTS
if "active" not in st.session_state:
    st.session_state.active = st.session_state.alerts[0]
if "voiceQuery" not in st.session_state:
    st.session_state.voiceQuery = ""
if "voiceResp" not in st.session_state:
    st.session_state.voiceResp = None
if "thinking" not in st.session_state:
    st.session_state.thinking = False


# Sidebar: backend URL and probe
st.sidebar.header("Settings")
backend_url = st.sidebar.text_input("Backend URL", value=os.getenv("VOICEGUARD_BACKEND", "http://localhost:8000/"))
if backend_url:
    backend_ok = probe_backend(backend_url)
else:
    backend_ok = None

st.sidebar.markdown("---")
st.sidebar.write("Tips:")
st.sidebar.write("- Click an entry in the Alert Ledger to inspect.")
st.sidebar.write("- Use the voice agent at the right to get a simulated response.")


# Top ticker
st.markdown("<div style='background:#0f1724;padding:6px;color:#cbd5e1;font-family:monospace;'><marquee>" + " · ".join(TICKER) + "</marquee></div>", unsafe_allow_html=True)


col_main, col_side = st.columns([7, 5])

with col_main:
    st.subheader("Live Risk Assessment")
    active = st.session_state.active

    sev = SEV_TOKEN.get(active["severity"], {})

    st.write(f"### {active['disaster_type']}")
    st.write(f"**Location:** {active['location']} — **Last update:** {active['timestamp']}")
    st.write(f"**Severity:** {active['severity']} · {sev.get('label','')}")

    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Posts analyzed", active["posts"])
    m2.write("Source")
    m2.write(SOURCE_LABEL.get(active["source"], active["source"]))
    m3.write("Confidence")
    m3.write("0.87")
    m4.write("Last update")
    m4.write(active["timestamp"])

    # Radar (SVG)
    radar_svg = f"""
    <svg width='100%' height='300' viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'>
      <circle cx='100' cy='100' r='90' fill='none' stroke='#cbd5e1' stroke-opacity='0.12'/>
      <line x1='10' y1='100' x2='190' y2='100' stroke='#cbd5e1' stroke-opacity='0.12'/>
      <circle cx='70' cy='60' r='4' fill='#f97316'/>
      <circle cx='130' cy='80' r='5' fill='#f97316'/>
      <circle cx='95' cy='130' r='4' fill='#f97316'/>
    </svg>
    """
    st.markdown(radar_svg, unsafe_allow_html=True)

    # Advisory
    if active["severity"] == "HIGH":
        advisory = f"EVACUATE low-lying zones near {active['location']}. Avoid the coastline. Follow SDRF instructions."
    elif active["severity"] == "MEDIUM":
        advisory = f"Stay alert for {active['disaster_type'].lower()} updates near {active['location']}. Keep emergency kit ready."
    else:
        advisory = f"Conditions stable. Monitor IMD bulletins for {active['location']}."
    st.info(advisory)

    st.markdown("---")

    # Alert ledger
    st.subheader(f"Alert Ledger — {len(st.session_state.alerts)} entries")
    for a in st.session_state.alerts:
        is_active = a["id"] == st.session_state.active["id"]
        btn = st.button(f"{a['timestamp']} — {a['disaster_type']} ({a['location']}) — {a['posts']} posts", key=f"btn_{a['id']}")
        if btn:
            st.session_state.active = a

with col_side:
    st.subheader("Signal Telemetry")
    telemetry = {"Twitter / X": 62, "WhatsApp groups": 48, "Local news feeds": 31, "IMD bulletins": 21, "Voice hotline": 14}
    for k, v in telemetry.items():
        st.write(f"{k} — {v}")
        st.progress(min(100, v) / 100.0)

    st.markdown("---")

    # Voice agent
    st.subheader("Voice Agent — KAN · ENG · TUL")
    st.write("Ask in your own language.")
    st.session_state.voiceQuery = st.text_input("", value=st.session_state.voiceQuery, key="voice_input")
    if st.button("Ask"):
        q = st.session_state.voiceQuery.strip()
        if q:
            st.session_state.thinking = True
            st.experimental_rerun()
    if st.session_state.thinking:
        # simulate processing
        time.sleep(0.7)
        active = st.session_state.active
        st.session_state.voiceResp = (
            f"Signals near {active['location'].split(' / ')[0]} indicate a {active['severity'].lower()} {active['disaster_type'].lower()} risk. "
            f"Move to higher ground, avoid the coast. {active['posts']} community reports verified in the last hour."
        )
        st.session_state.thinking = False

    if st.session_state.voiceResp:
        st.success("Agent response")
        st.write(st.session_state.voiceResp)
    else:
        st.write("Awaiting query · agent online")

    st.markdown("---")
    now = datetime.utcnow()
    st.write(f"Backend: {'ONLINE' if backend_ok else 'OFFLINE' if backend_ok is not None else 'N/A'} — UTC {now.strftime('%H:%M:%S')}")

