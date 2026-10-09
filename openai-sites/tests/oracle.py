"""Run the unchanged canonical Python engine using synthetic inputs only."""
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try:
    from rumbo.core import Engine,RumboError,canonical
except ModuleNotFoundError:
    import runpy
    oracle=runpy.run_path(str(Path(__file__).with_name('oracle_core.py')))
    Engine,RumboError,canonical=(oracle[name] for name in ('Engine','RumboError','canonical'))
request=json.loads(sys.stdin.buffer.read())
if request['mode']=='canonical':
    print(json.dumps([canonical(v) for v in request['values']]))
else:
    with tempfile.TemporaryDirectory() as root:
        result=[]
        for op in request['steps']:
            engine=Engine(root,op.get('actor','owner'),op.get('role','human'),clock=lambda:op.get('now',1000))
            try:
                value=engine.snapshot() if op['action']=='snapshot' else engine.artifact_view(op['args']) if op['action']=='read' else engine.execute(op['action'],op['args'])
                result.append({'ok':value})
            except RumboError as err:result.append({'error':err.code,'message':err.message})
        print(canonical(result))
