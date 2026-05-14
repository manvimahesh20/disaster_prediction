import sys, types, contextlib, traceback
from pathlib import Path

# Stub backend.sms to avoid Twilio import errors
sms = types.ModuleType('backend.sms')
def send_sms_alert(*args, **kwargs):
    return None
sms.send_sms_alert = send_sms_alert
backend_mod = types.ModuleType('backend')
backend_mod.sms = sms
sys.modules['backend'] = backend_mod
sys.modules['backend.sms'] = sms

log_path = Path(__file__).resolve().parent / 'pipeline_run_output.txt'

with open(log_path, 'w', encoding='utf-8') as f:
    try:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            import run_pipeline
            run_pipeline.main()
    except Exception:
        traceback.print_exc(file=f)

print('WROTE', str(log_path))
