import os
import time
import requests
from datetime import datetime
import streamlit as st
import json
from pathlib import Path


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


def fetch_history_once():
    """Fetch history from backend and update session state without overwriting user's active selection."""
    try:
        url = backend_url.rstrip("/") + "/history"
        r = requests.get(url, timeout=3)
        if not r.ok:
            return
        hist = r.json() or []
        if not isinstance(hist, list):
            return
        # Use last 50 entries
        new_alerts = hist[-50:]
        old_ids = [a.get("id") for a in st.session_state.get("alerts", [])]
        new_ids = [a.get("id") for a in new_alerts]
        if new_ids != old_ids:
            st.session_state.alerts = new_alerts
            # preserve active if its id is still present
            cur_active = st.session_state.get("active")
            if cur_active and cur_active.get("id") in new_ids:
                idx = new_ids.index(cur_active.get("id"))
                st.session_state.active = new_alerts[idx]
            else:
                if new_alerts:
                    st.session_state.active = new_alerts[-1]
    except Exception:
        pass


def _poller():
    import time
    while True:
        try:
            if backend_url:
                fetch_history_once()
        except Exception:
            pass
        time.sleep(max(1, int(st.session_state.get("auto_refresh_interval", 5))))


if "_poller_started" not in st.session_state:
    import threading
    t = threading.Thread(target=_poller, daemon=True)
    t.start()
    st.session_state["_poller_started"] = True


# Sidebar: backend URL and probe
st.sidebar.header("Settings")
backend_url = st.sidebar.text_input("Backend URL", value=os.getenv("VOICEGUARD_BACKEND", "http://localhost:8000/"))
if backend_url:
    backend_ok = probe_backend(backend_url)
else:
    backend_ok = None

# Auto-refresh controls
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False
if "auto_refresh_interval" not in st.session_state:
    st.session_state.auto_refresh_interval = 5

st.sidebar.checkbox("Auto refresh", value=st.session_state.auto_refresh, key="auto_refresh")
st.sidebar.number_input("Refresh interval (s)", min_value=1, max_value=60, value=st.session_state.auto_refresh_interval, step=1, key="auto_refresh_interval")

st.sidebar.markdown("---")
st.sidebar.write("Tips:")
st.sidebar.write("- Click an entry in the Alert Ledger to inspect.")
st.sidebar.write("- Use the voice agent at the right to get a simulated response.")
# Image verification quick UI on the sidebar
st.sidebar.markdown("---")
st.sidebar.header("🔍 Image Verification")
img_url = st.sidebar.text_input("Image URL to verify", value="")
if st.sidebar.button("Verify Image"):
    if img_url.strip():
        try:
            backend = backend_url.rstrip("/") + "/verify-image"
            r = requests.post(backend, json={"image_url": img_url}, timeout=10)
            if r.ok:
                data = r.json()
                verdict = data.get("verdict")
                conf = data.get("confidence", 0.0)
                reason = data.get("reasoning", "")
                sources = data.get("sources_found", 0)
                if verdict == "VERIFIED_REAL":
                    st.success(f"VERIFIED REAL — confidence={conf:.2f} — sources={sources}")
                    st.write(reason)
                else:
                    st.error(f"FLAGGED — confidence={conf:.2f} — sources={sources}")
                    st.write(reason)
            else:
                st.warning("Verification request failed")
        except Exception:
            st.exception("Verification request error")

# Misinformation log expander
with st.sidebar.expander("🚫 Misinformation Log"):
    try:
        backend = backend_url.rstrip("/") + "/misinformation-log"
        r = requests.get(backend, timeout=5)
        if r.ok:
            logs = r.json()
            if logs:
                for entry in logs[-20:][::-1]:
                    ts = entry.get("flagged_timestamp")
                    src = entry.get("source") or entry.get("id")
                    reason = entry.get("flagged_reason")
                    conf = entry.get("confidence", "n/a")
                    st.write(f"{ts} — {src} — {reason} — conf={conf}")
            else:
                st.write("No flagged posts recorded.")
        else:
            st.write("Could not fetch misinformation log")
    except Exception:
        st.write("Error fetching misinformation log")


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

    st.markdown("---")
    st.subheader("Scraper Console")
    data_file = Path(__file__).resolve().parents[1] / "nlp" / "scrapers" / "data" / "disaster_articles.jsonl"
    items = []
    if data_file.exists():
        try:
            with open(data_file, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        items.append(json.loads(ln))
                    except Exception:
                        continue
        except Exception:
            st.warning("Could not read scraped data file.")
    else:
        st.info(f"No scraped data file found at {data_file}")

    if items:
        recent = items[-200:]
        labels = []
        for it in recent:
            ts = it.get("timestamp") or it.get("published") or it.get("created_at") or ""
            title = it.get("title") or it.get("headline") or it.get("summary") or it.get("id") or "(no title)"
            labels.append(f"{ts} — {title[:80]}")

        sel_label = st.selectbox("Select scraped item", labels)
        sel_idx = labels.index(sel_label)
        item = recent[sel_idx]
        st.write(item.get("text") or item.get("summary") or item.get("description") or "")
        if item.get("image_url"):
            st.image(item.get("image_url"), use_column_width=True)
            if st.button("Verify this image", key=f"verify_{sel_idx}"):
                try:
                    verify_endpoint = backend_url.rstrip("/") + "/verify-image"
                    r = requests.post(verify_endpoint, json={"image_url": item.get("image_url")}, timeout=15)
                    if r.ok:
                        vr = r.json()
                        verdict = vr.get("verdict")
                        conf = vr.get("confidence", 0.0)
                        st.success(f"Verdict: {verdict} — confidence={conf:.2f}")
                        if vr.get("reasoning"):
                            st.write(vr.get("reasoning"))
                        sources = vr.get("sources_found") or vr.get("sources") or vr.get("news_items")
                        if sources:
                            st.write("Sources found:")
                            try:
                                for s in sources:
                                    link = s.get("link") if isinstance(s, dict) else s
                                    title = s.get("title") if isinstance(s, dict) else ""
                                    st.write(f"- {title} — {link}")
                            except Exception:
                                st.write(sources)
                    else:
                        st.warning("Verification request failed")
                except Exception:
                    st.exception("Verification request error")
        else:
            st.write("No image URL present in this item.")
        if st.button("Reload scraped items"):
            st.experimental_rerun()
    else:
        st.write("No scraped items available.")

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
    # suggestion buttons
    cols = st.columns(5)
    suggestions = ["🌊 Any floods?", "🌀 Cyclone warning?", "📍 Which areas affected?", "⚠️ What should I do?", "📊 How many reports?"]
    for i, s in enumerate(suggestions):
        if cols[i].button(s, key=f"sugg_{i}"):
            st.session_state.voiceQuery = s
            st.session_state.thinking = True
            st.experimental_rerun()

    st.session_state.voiceQuery = st.text_input("", value=st.session_state.voiceQuery, key="voice_input")
    if st.button("Ask"):
        q = st.session_state.voiceQuery.strip()
        if q:
            st.session_state.thinking = True
            st.experimental_rerun()

    # client-side intent detection (mirrors backend parse_voice_query)
    def detect_intent(q: str) -> str:
        if not q:
            return "general"
        qq = q.lower()
        if any(kw in qq for kw in ["what to do", "what should i do", "advice", "how to"]):
            return "what_to_do"
        if any(kw in qq for kw in ["which areas", "which areas are", "which places", "where are"]):
            return "which_areas"
        if any(kw in qq for kw in ["how many", "how many reports", "count", "reports"]):
            return "how_many"
        if any(kw in qq for kw in ["how bad", "severity", "how severe", "danger"]):
            return "how_bad"
        return "general"

    intent = detect_intent(st.session_state.voiceQuery)
    st.write(f"Intent detected: **{intent}**")
    if st.session_state.thinking:
        # simulate processing
        time.sleep(0.7)
        active = st.session_state.active
        # call backend voice-check if backend available
        try:
            if backend_url:
                r = requests.post(backend_url.rstrip("/") + "/voice-check", json={"query": st.session_state.voiceQuery}, timeout=10)
                if r.ok:
                    data = r.json()
                    st.session_state.voiceResp = data.get("voice_response") or data.get("advice") or str(data)
                    # attempt audio playback via gTTS
                    try:
                        from gtts import gTTS
                        import tempfile
                        tfn = tempfile.gettempdir() + "/voiceguard_response.mp3"
                        t = gTTS(st.session_state.voiceResp)
                        t.save(tfn)
                        st.audio(tfn)
                    except Exception:
                        pass
                else:
                    st.session_state.voiceResp = (
                        f"Signals near {active['location'].split(' / ')[0]} indicate a {active['severity'].lower()} {active['disaster_type'].lower()} risk. "
                        f"Move to higher ground, avoid the coast. {active['posts']} community reports verified in the last hour."
                    )
            else:
                st.session_state.voiceResp = (
                    f"Signals near {active['location'].split(' / ')[0]} indicate a {active['severity'].lower()} {active['disaster_type'].lower()} risk. "
                    f"Move to higher ground, avoid the coast. {active['posts']} community reports verified in the last hour."
                )
        except Exception:
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

    # Sidebar: Sources Status and Manual Alert
    with st.sidebar.expander("Sources Status"):
        try:
            if backend_url:
                r = requests.get(backend_url.rstrip("/") + "/sources-status", timeout=3)
                if r.ok:
                    status = r.json()
                    for k, v in status.items():
                        st.write(f"{k}: {v.get('status')} — {v.get('count')} posts")
                else:
                    st.write("Could not fetch sources status")
            else:
                st.write("Backend not configured")
        except Exception:
            st.write("Error fetching sources status")

    with st.sidebar.expander("Manual Alert"):
        if st.button("Trigger Manual Flood Alert"):
            try:
                payload = {"disaster_type": "Flood", "location": "Mangalore", "severity": "HIGH"}
                if backend_url:
                    r = requests.post(backend_url.rstrip("/") + "/manual-alert", json=payload, timeout=5)
                    if r.ok:
                        st.success("Alert triggered!")
                    else:
                        st.warning("Manual alert failed")
                else:
                    st.warning("Backend not configured")
            except Exception:
                st.exception("Manual alert failed")

