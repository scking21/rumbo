"""Deterministic, explicitly synthetic reviewer fixture; no model or network calls."""
from pathlib import Path
from .core import Engine, RumboError

DEMO_TIME = 1790812800.0


def create_demo(root):
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    if (root/'.rumbo/state.sqlite3').exists():
        raise RumboError('CONTRACT_EXISTS','Use a new empty folder for the synthetic demo')
    if any(root.iterdir()):
        raise RumboError('DEMO_NOT_EMPTY','Use a new empty folder; existing files are never overwritten')
    now=lambda:DEMO_TIME
    owner=Engine(root,'demo-owner','human',clock=now)
    maker=Engine(root,'demo-maker','worker',clock=now)
    reviewer=Engine(root,'demo-reviewer','reviewer',clock=now)
    tasks=[
        dict(id='export',title='Ship the CSV export',dependencies=[],acceptance=[dict(id='header',kind='file_contains',value='name,amount')]),
        dict(id='dependencies',title='Keep the approved dependency baseline',dependencies=[],acceptance=[dict(id='baseline',kind='json_equals',key='dependencies',value={})]),
        dict(id='review',title='Review export semantics',dependencies=['export'],acceptance=[dict(id='semantics',kind='manual_review',prompt='Inspect quoting and row semantics; report remaining limitations')]),
        dict(id='docs',title='Document the accepted export',dependencies=['export'],acceptance=[dict(id='usage',kind='file_contains',value='CSV export')]),
        dict(id='accessibility',title='Check keyboard navigation',dependencies=[],acceptance=[dict(id='keyboard',kind='manual_review',prompt='Exercise keyboard navigation in the real product')]),
        dict(id='release',title='Prepare the release',dependencies=['dependencies','review'],acceptance=[dict(id='ready',kind='file_contains',value='reviewed')]),
    ]
    owner.execute('create_contract',dict(project_id='synthetic-csv-demo',goal='Ship a CSV export with evidence the human can inspect',original_request='Synthetic reviewer scenario: export CSV, preserve the dependency baseline, and keep final acceptance with the owner.',decision_owner='demo-owner',constraints=['No new dependencies','Human review before release','Synthetic data only'],tasks=tasks,demo=True))
    (root/'sample.csv').write_text('name,amount\nSynthetic Ada,12\n',encoding='utf-8')
    (root/'package.json').write_text('{"dependencies":{"synthetic-new-package":"1.0.0"}}\n',encoding='utf-8')
    (root/'guide.txt').write_text('CSV export is documented here.\n',encoding='utf-8')
    for task,path in [('export','sample.csv'),('dependencies','package.json'),('review','sample.csv'),('docs','guide.txt')]:
        maker.execute('claim_task',dict(task_id=task,contract_revision=1,lease_seconds=3600))
        maker.execute('submit_artifact',dict(task_id=task,contract_revision=1,path=path))
        maker.execute('run_checks',dict(task_id=task,contract_revision=1,artifact_revision=1))
        if task in ('export','docs'):
            owner.execute('decide',dict(task_id=task,contract_revision=1,artifact_revision=1,outcome='accepted',reason='Synthetic human decision for this exact artifact and evidence'))
    reviewer.execute('submit_review',dict(task_id='review',contract_revision=1,artifact_revision=1,check_id='semantics',outcome='pass',detail='Synthetic reviewer assertion: inspected the example row, not a production test suite'))
    maker.execute('request_decision',dict(task_id='review',question='Will you accept this exact export after inspecting the reviewer assertion?'))
    maker.execute('request_decision',dict(task_id='dependencies',question='The fixture adds a dependency. Should the maker remove it or should the owner revise the contract?'))
    (root/'guide.txt').write_text('Documentation changed after acceptance.\n',encoding='utf-8')
    return owner.snapshot()
