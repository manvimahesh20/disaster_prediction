"""Runner for `pipeline.run_pipeline()`.

Usage: python run_pipeline.py

Loads environment from `.env`, runs the pipeline, and prints JSON result.
"""
import json
import importlib.util
from pathlib import Path
from dotenv import load_dotenv


def load_pipeline_module():
    here = Path(__file__).resolve().parent
    module_path = here / "pipeline.py"
    spec = importlib.util.spec_from_file_location("voiceguard_pipeline", str(module_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    load_dotenv()
    pipeline = load_pipeline_module()
    res = pipeline.run_pipeline()
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
