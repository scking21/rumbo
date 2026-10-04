"""Verify an owner-downloaded hosted backup; stdin input, no writes or network."""
import base64,hashlib,json,sys

# Each committed event can reference one immutable upload, plus header/footer.
MAX_EVENTS=10000
MAX_RECORDS=2*MAX_EVENTS+2

def verify(source):
    records=[]
    for raw in source:
        if len(raw)>2*1024*1024:raise ValueError('Oversized export record')
        records.append(json.loads(raw))
        if len(records)>MAX_RECORDS:raise ValueError('Too many export records')
    if not records or records[0].get('format')!='rumbo-sites-export-v1':raise ValueError('Unsupported export')
    head='0'*64;events=0;artifacts={};required=set()
    for row in records[1:-1]:
        if row['type']=='event':
            events+=1
            if row['seq']!=events or row['previous']!=head or hashlib.sha256((head+'\n'+row['payload']).encode()).hexdigest()!=row['digest']:raise ValueError('Ledger integrity failed')
            event=json.loads(row['payload']);artifact=event.get('data',{}).get('artifact')
            if artifact:required.add(artifact['sha256'])
            head=row['digest']
        elif row['type']=='artifact':
            data=base64.b64decode(row['base64'],validate=True)
            if len(data)!=row['size'] or len(data)>128*1024 or hashlib.sha256(data).hexdigest()!=row['digest'] or row['digest'] in artifacts:raise ValueError('Artifact integrity failed')
            artifacts[row['digest']]=len(data)
        else:raise ValueError('Unexpected export record')
    end=records[-1]
    if end!={'type':'end','complete':True,'events':events,'artifacts':len(artifacts),'ledger_head':head}:raise ValueError('Incomplete export')
    header=records[0]
    if header['events']!=events or header['artifacts']!=len(artifacts) or header['ledger_head']!=head or not required.issubset(artifacts):raise ValueError('Export manifest mismatch')
    if sum(artifacts.values())>64*1024*1024:raise ValueError('Artifact quota exceeded')
    return {'verified':True,'events':events,'artifacts':len(artifacts),'ledger_head':head,'notice':'Byte integrity only; not external witnessing or correctness'}
if __name__=='__main__':
    try:print(json.dumps(verify(sys.stdin)))
    except (ValueError,KeyError,TypeError) as error:print('Invalid export: '+str(error),file=sys.stderr);sys.exit(1)
