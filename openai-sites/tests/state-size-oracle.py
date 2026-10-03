"""Canonical replay/append measurement for supplied synthetic valid histories."""
import hashlib,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try:
    from rumbo.core import Engine, RumboError, canonical
except ModuleNotFoundError:
    import runpy
    oracle=runpy.run_path(str(Path(__file__).with_name('oracle_core.py')))
    Engine,RumboError,canonical=(oracle[name] for name in ('Engine', 'RumboError', 'canonical'))
request=json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix='rumbo-size-') as root:
    engine=Engine(root,'owner','human',clock=lambda:1000)
    with engine._db() as db:db.executemany('INSERT INTO events VALUES(?,?,?,?)',[(r['seq'],r['payload'],r['previous'],r['digest']) for r in request['rows']])
    state=engine.snapshot();raw=canonical(state)
    result={'state_bytes':len(raw.encode()),'state_digest':hashlib.sha256(raw.encode()).hexdigest(),'events':state['events_count'],'requests':len(state['requests'])}
    try:
        after=engine.execute('request_decision',{'task_id':'one','question':'q'})
        result['append']={'events':after['events_count'],'requests':len(after['requests'])}
    except RumboError as error:result['append']={'error':error.code}
    print(canonical(result))
