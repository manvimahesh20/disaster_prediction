"""Run `disaster_orchestrator.run_once` periodically using APScheduler."""
import os
from dotenv import load_dotenv

load_dotenv()

INTERVAL_MINUTES = int(os.environ.get("SCHEDULE_MINUTES", "2"))

def main():
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except Exception:
        raise RuntimeError("apscheduler is required. Install via requirements.txt")

    try:
        from disaster_orchestrator import run_once
    except Exception:
        from voiceguard_ai.nlp.scrapers.disaster_orchestrator import run_once

    sched = BlockingScheduler()

    def job():
        print("Running scheduled scrape...")
        try:
            res = run_once()
            print("Scrape result:", res)
        except Exception as e:
            print("Scrape job failed:", e)

    sched.add_job(job, "interval", minutes=INTERVAL_MINUTES)
    print(f"Starting scheduler: running every {INTERVAL_MINUTES} minutes")
    sched.start()


if __name__ == "__main__":
    main()
