"""Local canonical-engine oracle; synthetic stdin inputs, no network/runtime."""
import hashlib, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from rumbo.core import Engine, RumboError, canonical
except ModuleNotFoundError:
    import runpy
    oracle=runpy.run_path(str(Path(__file__).with_name('oracle_core.py')))
    Engine,RumboError,canonical=(oracle[name] for name in ('Engine', 'RumboError', 'canonical'))
request=json.load(sys.stdin)
results=[]
with tempfile.TemporaryDirectory(prefix='rumbo-parity-') as root:
    for op in request['steps']:
        engine=Engine(root,op['actor'],op['role'],clock=lambda:op['now'])
        if op.get('fault') in ('upload_before_write','upload_after_write'):
            original=engine._store_upload
            def faulty_upload(digest,data):
                if op['fault']=='upload_after_write':original(digest,data)
                raise RumboError('PATH_UNSAFE','Synthetic interrupted upload')
            engine._store_upload=faulty_upload
        try:
            result={'ok':engine.snapshot() if op['action']=='snapshot' else engine.artifact_view(op['args']) if op['action']=='read' else engine.execute(op['action'],op['args'])}
        except RumboError as error:result={'error':error.code}
        except Exception as error:result={'exception':type(error).__name__,'message':str(error)}
        results.append(result)
print(canonical(results if request.get('full') else [{'digest':hashlib.sha256(canonical(result).encode()).hexdigest(),'error':result.get('error'),'exception':result.get('exception')} for result in results]))
