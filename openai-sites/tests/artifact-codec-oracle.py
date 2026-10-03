"""Synthetic raw-byte artifact decoding reference."""
import base64,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try:
    from rumbo.core import artifact_json, canonical
except ModuleNotFoundError:
    import runpy
    oracle=runpy.run_path(str(Path(__file__).with_name('oracle_core.py')))
    artifact_json,canonical=(oracle[name] for name in ('artifact_json', 'canonical'))
out=[]
for encoded in json.load(sys.stdin):
    try:out.append({'ok':artifact_json(base64.b64decode(encoded))})
    except (ValueError,UnicodeError,RecursionError):out.append({'error':'INVALID_ARTIFACT_JSON'})
print(canonical(out))
