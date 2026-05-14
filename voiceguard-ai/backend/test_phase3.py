import json
from pathlib import Path

from fastapi.testclient import TestClient

from .main import app

client = TestClient(app)


def test_scrape_all_and_pipeline():
    # scrape_all via pipeline run should return structured result
    try:
        from nlp.scraper import scrape_all
    except Exception:
        from voiceguard_ai.nlp.scraper import scrape_all

    posts = scrape_all()
    assert isinstance(posts, list)

    # run pipeline
    resp = client.get("/check-now")
    assert resp.status_code == 200
    data = resp.json()
    assert "disaster_type" in data
    print("PASS: pipeline run")


def test_voice_check_queries():
    resp = client.post("/voice-check", json={"query": "What should I do?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "voice_response" in data

    resp2 = client.post("/voice-check", json={"query": "How many reports?"})
    assert resp2.status_code == 200
    print("PASS: voice check endpoints")


def test_manual_alert_and_sources_status():
    resp = client.post("/manual-alert", json={"disaster_type": "Flood", "location": "Mangalore", "severity": "HIGH"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"

    resp2 = client.get("/sources-status")
    assert resp2.status_code == 200
    print("PASS: manual alert and sources status")


if __name__ == "__main__":
    test_scrape_all_and_pipeline()
    test_voice_check_queries()
    test_manual_alert_and_sources_status()
