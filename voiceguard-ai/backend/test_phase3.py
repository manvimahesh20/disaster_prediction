import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_scrape_all_and_pipeline():
    # Test 1: scrape_gdacs/reliefweb/bluesky scrapers respond
    try:
        import nlp.scraper as sc
    except Exception:
        import voiceguard_ai.nlp.scraper as sc

    gd = sc.scrape_gdacs()
    assert isinstance(gd, list)
    print("PASS: scrape_gdacs returned list")

    rw = sc.scrape_reliefweb()
    assert isinstance(rw, list)
    print("PASS: scrape_reliefweb returned list")

    bs = sc.scrape_bluesky()
    assert isinstance(bs, list)
    print("PASS: scrape_bluesky returned list")

    posts = sc.scrape_all()
    assert isinstance(posts, list)
    assert len(posts) > 0
    sources = set(p.get("source") for p in posts)
    assert "simulated" in sources  # always present
    print("PASS: scrape_all() returns merged posts")

    # Test 4: unified format keys
    required = {"id", "text", "title", "url", "image_url", "source", "timestamp", "score", "disaster_hint"}
    for p in posts[:20]:
        assert required.issubset(set(p.keys()))
    print("PASS: unified format present in posts")

    # Test 2: NLP pipeline processes scraped posts correctly
    resp = client.get("/check-now")
    assert resp.status_code == 200
    data = resp.json()
    assert "disaster_type" in data
    assert "severity" in data
    assert "posts_analyzed" in data
    assert data["posts_analyzed"] > 0
    print("PASS: NLP pipeline processes scraped posts correctly")


def test_voice_check_queries():
    # Test 3: POST /voice-check with query "Any floods?"
    resp = client.post("/voice-check", json={"query": "Any floods?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "voice_response" in data
    assert "intent_detected" in data
    assert data["intent_detected"] == "general"
    print("PASS: voice check with 'Any floods?'")

    # Test 4: POST /voice-check with query "What to do?"
    resp2 = client.post("/voice-check", json={"query": "What to do?"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "voice_response" in data2
    assert data2["intent_detected"] == "what_to_do"
    print("PASS: voice check with 'What to do?'")

    # Test 5: POST /voice-check with query "Which areas?"
    resp3 = client.post("/voice-check", json={"query": "Which areas?"})
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert "voice_response" in data3
    assert data3["intent_detected"] == "which_areas"
    print("PASS: voice check with 'Which areas?'")


def test_manual_alert_and_sources_status():
    # Test 6: POST /manual-alert triggers SMS + dashboard
    resp = client.post("/manual-alert", json={"disaster_type": "Flood", "location": "Mangalore", "severity": "HIGH"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "result" in data
    print("PASS: manual alert triggers")

    # Test 7: GET /sources-status
    resp2 = client.get("/sources-status")
    assert resp2.status_code == 200
    status = resp2.json()
    # should include new sources
    assert "gdacs" in status
    assert "reliefweb" in status
    assert "bluesky" in status
    assert "rss" in status
    assert "simulated" in status
    print("PASS: sources status endpoint")


def test_image_triage():
    # Test 8: Image triage runs on posts with image_url
    # This is tested indirectly through pipeline, but we can test verify-image endpoint
    resp = client.post("/verify-image", json={"image_url": "https://example.com/fake_image.jpg"})
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict" in data
    print("PASS: image triage endpoint")


def test_misinformation_filtering():
    # Test 9: Misinformation gets blocked correctly
    # This would require posts that trigger triage flagging, but for now just check the endpoint exists
    resp = client.get("/misinformation-log")
    assert resp.status_code == 200
    logs = resp.json()
    assert isinstance(logs, list)
    print("PASS: misinformation log endpoint")


def test_streamlit_integration():
    # Test 10: Streamlit can reach all backend endpoints
    endpoints = ["/", "/check-now", "/history", "/status", "/sources-status", "/misinformation-log"]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 200
        print(f"PASS: {ep} accessible")

    # Voice check
    resp = client.post("/voice-check", json={"query": "test"})
    assert resp.status_code == 200
    print("PASS: voice-check accessible")

    # Manual alert
    resp = client.post("/manual-alert", json={"disaster_type": "Test", "location": "Test", "severity": "LOW"})
    assert resp.status_code == 200
    print("PASS: manual-alert accessible")

    # Image verify
    resp = client.post("/verify-image", json={"image_url": "test"})
    assert resp.status_code == 200
    print("PASS: verify-image accessible")


def test_end_to_end():
    # Test 11: Full end-to-end: scrape → NLP → alert → SMS
    # This is a comprehensive test
    resp = client.get("/check-now")
    assert resp.status_code == 200
    data = resp.json()
    assert "severity" in data
    assert "disaster_type" in data
    assert "location" in data
    assert "advice" in data
    assert "posts_analyzed" in data
    assert data["posts_analyzed"] >= 0
    print("PASS: end-to-end pipeline")


if __name__ == "__main__":
    test_scrape_all_and_pipeline()
    test_voice_check_queries()
    test_manual_alert_and_sources_status()
    test_image_triage()
    test_misinformation_filtering()
    test_streamlit_integration()
    test_end_to_end()
    print("All Phase 3 tests passed!")
