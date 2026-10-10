#!/usr/bin/env python3
"""CI-only Docker smoke using synthetic data, no public ports or real credentials.

Builds the local image, exercises a read-only nonroot container, restart and
backup/restore, and checks nginx syntax with a temporary one-day fixture cert.
No provider calls are possible: containers use --network none. Nothing deploys.
"""
import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def run(*command,check=True):
    result=subprocess.run(command,cwd=ROOT,check=False,text=True,capture_output=True)
    if check and result.returncode:
        # This script operates on synthetic fixtures only; bounded failure output
        # is needed to diagnose CI image/proxy startup, never live service logs.
        print(result.stdout[-6000:]);print(result.stderr[-6000:])
        result.check_returncode()
    return result


@contextmanager
def synthetic_tree(tag, container):
    folder=Path(tempfile.mkdtemp(prefix='rumbo-ci-only-'))
    try:yield folder
    finally:
        run('docker','rm','--force',container,check=False)
        projects=folder/'projects'
        if projects.exists():
            # Remove only this test's UID10001-owned generated state before the
            # runner-owned temporary directory is discarded. No real data paths.
            run('docker','run','--rm','--network','none','--user','10001:10001','--mount',f'type=bind,src={projects},dst=/cleanup','--entrypoint','python',tag,'-c',"import shutil; shutil.rmtree('/cleanup/fixture/.rumbo',ignore_errors=True)",check=False)
        shutil.rmtree(folder)


def main():
    if not shutil.which('docker') or not shutil.which('openssl'):
        raise SystemExit('Docker and OpenSSL are required; this CI gate must not silently skip')
    tag='rumbo-smoke-'+uuid.uuid4().hex[:12]
    container=tag+'-app'
    try:
        run('docker','build','--tag',tag,'--file','deploy/Dockerfile','.')
        with synthetic_tree(tag,container) as folder:
            temp=Path(folder);temp.chmod(0o755)
            projects=temp/'projects';projects.mkdir();projects.chmod(0o755)
            project=projects/'fixture';project.mkdir();project.chmod(0o777) # Synthetic CI only; production runbook requires UID10001 ownership.
            secret=temp/'secret';secret.write_text('synthetic-client-secret-no-provider-account\n');secret.chmod(0o644)
            config=dict(mode='oauth',log_requests=True,public_url='https://ci.rumbo.test/mcp',issuer='https://auth.rumbo.test',introspection_url='https://auth.rumbo.test/introspect',introspection_client_id='synthetic-client',introspection_secret_env='RUMBO_INTROSPECTION_SECRET',principals=[dict(subject='synthetic-subject',actor='maker',role='worker',root='/var/lib/rumbo/projects/fixture')])
            conf=temp/'server.json';conf.write_text(json.dumps(config));conf.chmod(0o644)
            def start():
                run('docker','run','--detach','--name',container,'--network','none','--read-only','--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:size=32m,mode=1777','--mount',f'type=bind,src={conf},dst=/etc/rumbo/server.json,readonly','--mount',f'type=bind,src={projects},dst=/var/lib/rumbo/projects','--mount',f'type=bind,src={secret},dst=/run/secrets/mcp,readonly','--env','RUMBO_INTROSPECTION_SECRET_FILE=/run/secrets/mcp',tag)
                deadline=time.monotonic()+40
                while time.monotonic()<deadline:
                    if run('docker','exec',container,'python','/app/deploy/healthcheck.py',check=False).returncode==0:return
                    time.sleep(1)
                raise RuntimeError('Synthetic container did not become locally ready')
            start()
            contract=dict(project_id='ci-fixture',goal='Synthetic deployment smoke',original_request='Fixture data only',decision_owner='owner',constraints=[],tasks=[dict(id='one',title='One task',dependencies=[],acceptance=[dict(id='content',kind='file_contains',value='fixture')])])
            code="from rumbo.core import Engine; r='/var/lib/rumbo/projects/fixture'; Engine(r,'owner','human').execute('create_contract',"+repr(contract)+"); e=Engine(r,'maker','worker'); e.execute('claim_task',dict(task_id='one',contract_revision=1,lease_seconds=300)); e.execute('ingest_artifact',dict(task_id='one',contract_revision=1,filename='fixture.txt',content='fixture')); e.execute('run_checks',dict(task_id='one',contract_revision=1,artifact_revision=1))"
            run('docker','exec',container,'python','-c',code)
            run('docker','rm','--force',container)
            start()
            state=json.loads(run('docker','exec',container,'python','-m','rumbo','--root','/var/lib/rumbo/projects/fixture','state').stdout)
            assert state['project_id']=='ci-fixture' and state['tasks'][0]['status']=='checks_passed'
            run('docker','exec',container,'python','-m','rumbo.backup','backup','--root','/var/lib/rumbo/projects/fixture','--destination','/tmp/fixture.zip')
            run('docker','exec',container,'python','-m','rumbo.backup','restore','--archive','/tmp/fixture.zip','--destination','/tmp/restored')
            restored=json.loads(run('docker','exec',container,'python','-m','rumbo','--root','/tmp/restored','state').stdout)
            assert restored['ledger_head']==state['ledger_head'] and restored['tasks'][0]['status']=='checks_passed'
            run('docker','rm','--force',container)
            # Only fixture TLS material, isolated from accounts and deleted below.
            tls=temp/'tls';tls.mkdir();tls.chmod(0o755)
            run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'privkey.pem'),'-out',str(tls/'fullchain.pem'),'-days','1','-subj','/CN=ci.rumbo.test')
            for path in tls.iterdir():path.chmod(0o644)
            proxy=temp/'nginx.conf';proxy.write_text((ROOT/'deploy/nginx.conf.template').read_text().replace('__APP_HOST__','ci.rumbo.test'));proxy.chmod(0o644)
            run('docker','run','--rm','--network','none','--read-only','--user','101:101','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:size=32m,mode=1777','--add-host','app:127.0.0.1','--mount',f'type=bind,src={proxy},dst=/etc/nginx/nginx.conf,readonly','--mount',f'type=bind,src={tls},dst=/run/tls,readonly','--entrypoint','nginx','nginx:1.28-alpine','-t')
            print('PASS: nonroot/read-only container health, persisted restart, uploaded artifact backup/restore and nginx syntax; no public port/provider/account used')
    finally:
        run('docker','rm','--force',container,check=False)
        run('docker','image','rm',tag,check=False)

if __name__=='__main__':main()
