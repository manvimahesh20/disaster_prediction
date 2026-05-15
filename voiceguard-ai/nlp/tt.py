import os
import sys
import runpy
import subprocess

# Ensure voiceguard-ai package path
proj = os.getcwd()
modpath = os.path.join(proj, 'voiceguard-ai')
if modpath not in sys.path:
    sys.path.insert(0, modpath)

# Optionally enable mock SMS to be safe
os.environ['MOCK_SMS'] = '1'
# Run the pipeline module and get functions
ns = runpy.run_path(os.path.join(modpath, 'nlp', 'pipeline.py'))
run_pipeline = ns.get('run_pipeline')
build_tts = ns.get('build_tts_sentence')

# Run pipeline (uses simulated posts)
result = run_pipeline(source='tts-run')
# Build TTS sentence from result
tts = build_tts(result.get('severity'), result.get('location'), {'level': result.get('severity'), 'disaster_type': result.get('disaster_type')})
text = tts.get('tts_sentence', '')
print('TTS text:')
print(text)

# Clean up quotes for PowerShell double-quoted string
ps_text = text.replace('"', "'")

# Call PowerShell to speak the text via System.Speech (local TTS)
cmd = [
    'powershell',
    '-NoProfile',
    '-Command',
    f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak(\"{ps_text}\");"
]

try:
    subprocess.run(cmd, check=True)
except subprocess.CalledProcessError as e:
    print('PowerShell TTS failed:', e)