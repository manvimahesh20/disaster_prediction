import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from .main import app

client = TestClient(app)


def test_filter_news_results():
    # Load triage_pipeline by path to avoid package name mismatches
    import importlib.util
    import sys

    triage_path = Path(__file__).resolve().parents[1] / "nlp" / "triage_pipeline.py"
    spec = importlib.util.spec_from_file_location("voiceguard_triage", str(triage_path))
    triage = importlib.util.module_from_spec(spec)
    sys.modules["voiceguard_triage"] = triage
    spec.loader.exec_module(triage)
    filter_news_results = triage.filter_news_results
    NewsItem = getattr(triage, "NewsItem", tuple)

    mock = [
        {"link": "https://timesofindia.com/news/123", "title": "A", "snippet": "x"},
        {"link": "https://example.com/other", "title": "B", "snippet": "y"},
        {"link": "https://m.ndtv.com/article/1", "title": "C", "snippet": "z"},
    ]
    res = filter_news_results(mock)
    assert any(isinstance(r, NewsItem) for r in res)
    print("PASS: filter_news_results")


def test_run_pipeline_real_and_fake():
    # Load run_pipeline from triage_pipeline via file path
    import importlib.util
    import sys

    triage_path = Path(__file__).resolve().parents[1] / "nlp" / "triage_pipeline.py"
    spec = importlib.util.spec_from_file_location("voiceguard_triage", str(triage_path))
    triage = importlib.util.module_from_spec(spec)
    sys.modules["voiceguard_triage"] = triage
    spec.loader.exec_module(triage)
    run_pipeline = triage.run_pipeline

    # These tests are lightweight: we call the pipeline with known URLs.
    # In CI you may want to mock external APIs; here we just ensure the function runs.
    real_img = "https://upload.wikimedia.org/wikipedia/commons/3/3f/Flood.jpg"
    fake_img = "https://upload.wikimedia.org/wikipedia/commons/9/99/Example.jpg"

    r1 = run_pipeline(real_img)
    r2 = run_pipeline(fake_img)

    assert "verdict" in r1 and "confidence" in r1
    assert "verdict" in r2 and "confidence" in r2
    print("PASS: run_pipeline smoke tests")


def test_verify_image_endpoint():
    resp = client.post("/verify-image", json={"image_url": "https://example.com/img.jpg"})
    assert resp.status_code == 200
    print("PASS: /verify-image endpoint")


if __name__ == "__main__":
    test_filter_news_results()
    test_run_pipeline_real_and_fake()
    test_verify_image_endpoint()
