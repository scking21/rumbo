#!/usr/bin/env python3
"""Reproducible local, Sites review-draft, or final-gated archive. Never uploads."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
import subprocess
from urllib.parse import urlsplit
import zipfile

STAMP=(2026,10,1,0,0,0)
PUBLIC_FIELDS={'mcp_url','website_url','support_url','privacy_url','terms_url','video_url','attestations'}
GATES={'https_endpoint_verified','oauth_verified','domain_verified','publisher_verified','reviewer_account_verified','host_qa_verified','legal_pages_reviewed','video_access_verified'}


def validate_public_config(config):
    if not isinstance(config,dict) or set(config)!=PUBLIC_FIELDS:
        raise ValueError('Public package blocked: provide all production URLs and verification attestations; see docs/DEPLOYMENT.md')
    for name in PUBLIC_FIELDS-{'attestations'}:
        validate_url(name, config[name])
    attestations=config['attestations']
    if not isinstance(attestations,dict) or set(attestations)!=GATES or any(v is not True for v in attestations.values()):
        raise ValueError('Public package blocked: every documented external verification gate must be completed, not assumed')


def validate_url(name, value):
    if not isinstance(value,str):
        raise ValueError(name+' must be a verified HTTPS URL')
    u=urlsplit(value)
    host=(u.hostname or '').lower()
    if u.scheme!='https' or not host or u.username or u.password or u.fragment or host in ('localhost','example.com','example.org','example.net') or host.endswith(('.invalid','.example','.test','.localhost','.local')) or not re.fullmatch(r'[a-z0-9.-]+',host):
        raise ValueError(name+' must use an actual approved public HTTPS hostname, not a placeholder')
    labels=host.split('.')
    if len(labels)<2 or not re.fullmatch(r'[a-z][a-z0-9-]*',labels[-1]) or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in labels):
        raise ValueError(name+' must use a well-formed public DNS hostname')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(name+' must use a verified public DNS hostname, not an IP literal')
    if any(host.endswith('.'+reserved) for reserved in ('example.com','example.org','example.net')):
        raise ValueError(name+' cannot use a reserved example domain')
    if name=='mcp_url' and (u.path!='/mcp' or u.query):
        raise ValueError('mcp_url must identify the verified /mcp endpoint')


def read_plugin(root, review_profile):
    base=root/'openai-plugin/rumbo'
    files={}
    allowed={'plugin.json','mcp.json','README.md','.codex-plugin/plugin.json','assets/icon.svg','scripts/run_mcp.py','skills/coordinate-work/SKILL.md','skills/review-evidence/SKILL.md'}
    for path in base.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink packaging is forbidden')
        if path.is_file():
            relative=path.relative_to(base).as_posix()
            if '__pycache__' not in relative:
                if relative not in allowed:
                    raise ValueError('Unrecognized plugin input: '+relative+'; review the explicit package allowlist')
                files[relative]=path.read_bytes()
    required={'plugin.json','mcp.json','assets/icon.svg'}
    if review_profile=='local':
        required=allowed
    elif review_profile=='hosted':
        required=required|{'skills/coordinate-work/SKILL.md','skills/review-evidence/SKILL.md'}
    missing=required-files.keys()
    if missing:
        raise ValueError('Missing required plugin input: '+', '.join(sorted(missing)))
    manifest=json.loads(files['plugin.json'])
    def inspect_keys(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in ('hooks','apps','authorization','password','secret','token','test_credentials','reviewer_instructions'):
                    raise ValueError('Unsupported or sensitive plugin metadata: '+key)
                inspect_keys(item)
        elif isinstance(value,list):
            for item in value:inspect_keys(item)
    inspect_keys(manifest);inspect_keys(json.loads(files['mcp.json']))
    case_files={'local':'reviewer-cases-local.json','hosted':'reviewer-cases-hosted.json'}
    if review_profile == 'sites':
        files['LICENSE']=(root/'LICENSE').read_bytes()
        return files
    if review_profile not in case_files:
        raise ValueError('Unknown reviewer-case distribution profile')
    manifest['extensions']['com.openai']['review']={'test_cases':json.loads((root/'docs'/case_files[review_profile]).read_text())}
    files['plugin.json']=pretty(manifest)
    files['LICENSE']=(root/'LICENSE').read_bytes()
    return files


def pretty(value):
    return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()


def write_zip(target,files,prefix='rumbo'):
    # Validate the complete file set before creating the archive.
    seen=set()
    if len(files)>5000 or sum(map(len,files.values()))>512*1024*1024:
        raise ValueError('Archive limits exceeded')
    for name in files:
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or len(path.parts)>19 or name.casefold() in seen:
            raise ValueError('Unsafe archive path')
        seen.add(name.casefold())
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(prefix+'/'+name,STAMP)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
            archive.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    if target.stat().st_size>100*1024*1024:
        target.unlink()
        raise ValueError('Compressed archive limit exceeded')
    return hashlib.sha256(target.read_bytes()).hexdigest()


def build_local(root,target):
    root=Path(root);files=read_plugin(root, review_profile='local')
    required={'__init__.py','core.py','protocol.py','registry.py','installed.py','web/board.html'}
    missing={name for name in required if not (root/'rumbo'/name).is_file()}
    if missing:
        raise ValueError('Missing required local runtime input: '+', '.join(sorted(missing)))
    for path in (root/'rumbo').glob('*.py'):
        files['rumbo/'+path.name]=path.read_bytes()
    files['rumbo/web/board.html']=(root/'rumbo/web/board.html').read_bytes()
    files['DEPLOYMENT-GATES.json']=pretty(dict(status='local-review-candidate-not-public-submission',verified_external_gates={k:False for k in sorted(GATES)},note='No public endpoint, account, credentials, video or in-host visual verification is claimed.'))
    return write_zip(target,files)


def build_submission(root,target,config):
    validate_public_config(config)
    files=read_plugin(Path(root), review_profile='hosted')
    # Public package is skills + remote MCP + presentation, not local execution.
    files={k:v for k,v in files.items() if not k.startswith(('scripts/','.codex-plugin/'))}
    manifest=json.loads(files['plugin.json'])
    ext=manifest['extensions']['com.openai']
    ext['interface'].update(websiteURL=config['website_url'],supportURL=config['support_url'],privacyPolicyURL=config['privacy_url'],termsOfServiceURL=config['terms_url'])
    ext['review']['demo_recording_url']=config['video_url']
    ext['publication']['release_notes']=manifest['version']+': versioned contracts, expiring task claims, artifact-bound checks and reviewer assertions, human-owned acceptance and an interactive read-only project board.'
    files['plugin.json']=pretty(manifest)
    files['mcp.json']=pretty({'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'rumbo':{'type':'streamable-http','url':config['mcp_url']}}})
    files['README.md']=b'# Rumbo\n\nRemote project coordination and acceptance evidence. This archive has not been uploaded or submitted by its packaging script.\n'
    return write_zip(target,files)


LISTING_URLS={'website_url':'websiteURL','support_url':'supportURL',
              'privacy_url':'privacyPolicyURL','terms_url':'termsOfServiceURL'}


def sites_review_materials(root):
    """Read the actual hosted catalog, not the Python/local transport's tools."""
    protocol=(root/'openai-sites/worker/protocol.js').resolve().as_uri()
    command='import {toolDefinitions} from '+json.dumps(protocol)+'; process.stdout.write(JSON.stringify(toolDefinitions()));'
    try:
        result=subprocess.run(['node','--input-type=module','-e',command],
                              capture_output=True,text=True,check=True,timeout=30)
        catalog=json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,json.JSONDecodeError) as error:
        raise ValueError('Cannot inspect the actual Sites tool catalog; Node.js 24+ and checked-out Sites sources are required') from error
    names={tool['name'] for tool in catalog}
    source=json.loads((root/'openai-sites/reviewer-cases.json').read_text())
    cases={'positive':[],'negative':[]}
    for kind in cases:
        for case in source[kind+'_cases']:
            for field in ('id','prompt','expected'):
                if not isinstance(case.get(field),str) or not case[field].strip():
                    raise ValueError('Invalid Sites review case '+field)
            if not isinstance(case.get('tools'),list) or not all(isinstance(tool,str) and tool for tool in case['tools']):
                raise ValueError('Invalid Sites review case tools')
            if kind=='positive' and (not case['tools'] or not set(case['tools'])<=names):
                raise ValueError('Sites positive review case references an unavailable tool')
            item={'description':case['id']+': '+case['expected'],'prompt':case['prompt']}
            if kind=='positive':
                item.update(tools_triggered=', '.join(case['tools']),expected_behavior=case['expected'])
            cases[kind].append(item)
    return cases, sorted(names)


def validate_draft_manifests(root, files):
    try:
        from jsonschema import Draft202012Validator, ValidationError
    except ImportError as error:
        raise ValueError('Review-draft schema validation requires the jsonschema developer dependency') from error
    for name in ('plugin','mcp'):
        schema=json.loads((root/'schemas'/(name+'.schema.json')).read_text())
        try:
            Draft202012Validator(schema).validate(json.loads(files[name+'.json']))
        except ValidationError as error:
            raise ValueError('Invalid '+name+' manifest: '+error.message) from error
    # The portable schema deliberately does not constrain extension metadata.
    manifest=json.loads(files['plugin.json'])
    interface=manifest['extensions']['com.openai']['interface']
    for field, limit in {'displayName':30,'shortDescription':30,'longDescription':4000,'category':120}.items():
        value=interface.get(field)
        if not isinstance(value,str) or not value.strip() or len(value)>limit:
            raise ValueError('Invalid listing field: '+field)
    for field in ('logo','composerIcon'):
        path=interface.get(field,'')
        if not path.startswith('./') or path[2:] not in files:
            raise ValueError('Missing packaged listing asset: '+field)


def build_review_draft(root,target,config):
    """Prepare a Sites ZIP locally; missing portal/review steps stay pending."""
    root=Path(root); target=Path(target)
    if not isinstance(config,dict) or 'mcp_url' not in config or not set(config)<=PUBLIC_FIELDS:
        raise ValueError('Review draft needs mcp_url and accepts only documented URL fields and attestations')
    for name,value in config.items():
        if name!='attestations':validate_url(name,value)
    supplied=config.get('attestations',{})
    if not isinstance(supplied,dict) or not set(supplied)<=GATES or any(type(v) is not bool for v in supplied.values()):
        raise ValueError('Draft attestations must be known boolean values, never credentials or assumed verification')
    attestations={gate:supplied.get(gate,False) for gate in sorted(GATES)}
    files=read_plugin(root,review_profile='sites')
    files={k:v for k,v in files.items() if not k.startswith(('scripts/','.codex-plugin/','skills/'))}
    skill_base=root/'openai-plugin/sites-skills'
    allowed={'coordinate-work/SKILL.md','review-evidence/SKILL.md'}
    found=set()
    for path in skill_base.rglob('*'):
        if path.is_symlink():raise ValueError('Symlink packaging is forbidden')
        if path.is_file():
            relative=path.relative_to(skill_base).as_posix()
            if relative not in allowed:raise ValueError('Unexpected Sites skill input: '+relative)
            files['skills/'+relative]=path.read_bytes();found.add(relative)
    if found!=allowed:raise ValueError('Missing Sites-specific workflow skills')
    cases,names=sites_review_materials(root)
    for path,data in files.items():
        if path.endswith('SKILL.md'):
            mentioned=set(re.findall(r'\b(?:rumbo_[a-z_]+|open_project_board)\b',data.decode()))
            if not mentioned<=set(names):raise ValueError('Sites skill references an unavailable tool: '+path)
    manifest=json.loads(files['plugin.json'])
    # Source authorship is not a selected, verified legal publisher identity.
    manifest.pop('author',None)
    ext=manifest['extensions']['com.openai'];ext['interface'].pop('developerName',None)
    pending=['interface.developerName']
    for config_name,field in LISTING_URLS.items():
        ext['interface'].pop(field,None)
        if config_name in config:ext['interface'][field]=config[config_name]
        else:pending.append('interface.'+field)
    ext['review']={'test_cases':cases}
    if 'video_url' in config:ext['review']['demo_recording_url']=config['video_url']
    else:pending.append('review.demo_recording_url')
    ext['publication']={'release_notes':manifest['version']+' Sites review draft: uploaded-artifact workflow with project keys and server-issued worker sessions. Managed authentication, reviewer access and directory review remain unverified.'}
    files['plugin.json']=pretty(manifest)
    files['mcp.json']=pretty({'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'rumbo':{'type':'streamable-http','url':config['mcp_url']}}})
    files['README.md']=b'# Rumbo Sites review draft\n\nThis archive is for preparation and review. It is not submission-ready. Packaging performs no upload, portal verification, authentication, submission or publication. See the separate readiness report. No local filesystem access is provided.\n'
    validate_draft_manifests(root,files)
    report={'status':'review-draft-not-submission-ready','profile':'openai-sites-upload-workflow',
            'uploaded':False,'submitted':False,'endpoint':config['mcp_url'],
            'operator_attestations':attestations,
            'pending_external_gates':[gate for gate,value in attestations.items() if not value],
            'pending_review_fields':pending,'omitted_optional_fields':['author'],'source_tool_names':names,
            'validation_scope':'Local manifests, explicit file allowlists, actual source tool catalog and review-case references only; no endpoint or portal checks.',
            'review_case_status':'Scenarios from Sites sources, not evidence of authenticated managed-host execution.',
            'review_setup':json.loads((root/'openai-sites/reviewer-cases.json').read_text())['setup'],
            'portal_steps_not_performed':['Select verified developer identity and upload ZIP to create draft',
                'Verify domain and OAuth; scan tools and inspect automated findings',
                'Complete listing/legal decisions, reviewer access, managed test cases and video',
                'Owner review and final policy attestations before Submit for review'],
            'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                ['openai-plugin/rumbo/plugin.json','openai-sites/reviewer-cases.json',
                 'openai-sites/worker/protocol.js','openai-sites/worker/base-tools.js']}}
    digest=write_zip(target,files)
    report['archive_sha256']=digest
    target.with_suffix('.readiness.json').write_bytes(pretty(report))
    return digest


SITES_SOURCE_FILES={
    '.gitignore',
    '.openai/hosting.json',
    'LICENSE',
    'OPERATIONS.md',
    'PRIVACY.md',
    'README.md',
    'db/schema.ts',
    'drizzle.config.ts',
    'drizzle/0000_initial.sql',
    'drizzle/0001_guarded_project_deletion.sql',
    'drizzle/meta/0000_snapshot.json',
    'drizzle/meta/0001_snapshot.json',
    'drizzle/meta/_journal.json',
    'package-lock.json',
    'package.json',
    'playwright.config.mjs',
    'reviewer-cases.json',
    'scripts/assets.mjs',
    'scripts/browser-test-server.mjs',
    'scripts/build.sh',
    'scripts/run-review-cases.mjs',
    'scripts/validate-artifact.mjs',
    'scripts/verify-export.py',
    'scripts/verify-oracle.mjs',
    'tests/browser/owner.spec.mjs',
    'tests/board-dom.test.mjs',
    'tests/board-clipboard.test.mjs',
    'tests/board-focus.test.mjs',
    'tests/codec.test.mjs',
    'tests/decision-clock.test.mjs',
    'tests/deletion.test.mjs',
    'tests/engine.test.mjs',
    'tests/export.test.mjs',
    'tests/http.test.mjs',
    'tests/json-check-cache.test.mjs',
    'tests/oracle.py',
    'tests/oracle_core.py',
    'tests/owner-dom.test.mjs',
    'tests/privacy-http.test.mjs',
    'tests/review-cases.test.mjs',
    'tests/runtime.test.mjs',
    'tests/offline-runtime.mjs',
    'tests/offline-runtime.test.mjs',
    'WORKFLOW-VERIFICATION-2026-10-03.md',
    'tests/storage.test.mjs',
    'tests/support.mjs',
    'tests/workflows.test.mjs',
    'SEMANTIC-STRESS-2026-10-03.md',
    'scripts/measure-state-size.mjs',
    'scripts/run-semantic-stress.mjs',
    'tests/artifact-byte-codec.test.mjs',
    'tests/artifact-codec-oracle.py',
    'tests/semantic-boundaries.test.mjs',
    'tests/semantic-oracle-standalone.test.mjs',
    'tests/semantic-depth-regression.test.mjs',
    'tests/semantic-partial-failures.test.mjs',
    'tests/semantic-stress-oracle.py',
    'tests/semantic-stress-support.mjs',
    'tests/semantic-stress.test.mjs',
    'tests/state-size-oracle.py',
    'web/board.html',
    'web/owner.css',
    'web/owner.html',
    'web/owner.js',
    'worker/assets.js',
    'worker/base-tools.js',
    'worker/codec.js',
    'worker/engine.js',
    'worker/export.js',
    'worker/index.js',
    'worker/owner-auth.js',
    'worker/protocol.js',
    'worker/storage.js',
}

def build_source(root,target):
    root=Path(root);files={}
    for name in ['README.md','LICENSE','PRIVACY.md','SECURITY.md','pyproject.toml','requirements-owner.txt','requirements-authkit.txt','.gitignore','.dockerignore']:
        if (root/name).is_file():files[name]=(root/name).read_bytes()
    for dirname in ['rumbo','claude-plugin','tests','scripts','schemas','openai-plugin','docs','deploy','.github','.claude-plugin','openai-sites']:
        for path in (root/dirname).rglob('*'):
            relative=path.relative_to(root).as_posix()
            if dirname=='openai-sites' and any(part in {'node_modules','dist','qa-artifacts','test-results','playwright-report'} for part in path.relative_to(root/'openai-sites').parts):
                continue
            if path.is_symlink():raise ValueError('Symlink packaging forbidden')
            parts=path.relative_to(root).parts
            if any(part.lower() in {'.env','credentials.json','secrets.json','.netrc','.npmrc','.pypirc','.aws','.ssh','.gnupg'} or part.lower().startswith('.env.') for part in parts):
                raise ValueError('Potential credential input is forbidden in source packages: '+relative)
            if path.is_file() and not any(part in ('__pycache__','.rumbo','superpowers') for part in path.parts) and path.suffix.lower() not in ('.pyc','.sqlite3','.sqlite','.db','.zip','.tar','.gz','.pem','.key'):
                if dirname=='openai-sites' and path.relative_to(root/'openai-sites').as_posix() not in SITES_SOURCE_FILES:
                    raise ValueError('Unexpected Sites source input; review the explicit allowlist: '+relative)
                if dirname=='deploy' and path.relative_to(root/'deploy').as_posix() not in {'Dockerfile','compose.yml','nginx.conf.template','render.py','entrypoint.py','healthcheck.py','server-config.template.json','ci_smoke.py','render.yaml.template'}:
                    raise ValueError('Unexpected deployment input; never package live configuration or credentials: '+relative)
                files[relative]=path.read_bytes()
    return write_zip(target,files,prefix='rumbo-0.3.2-source')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=['local','source','review-draft','submission'],default='local');p.add_argument('--output',required=True);p.add_argument('--production-config');p.add_argument('--mcp-url',help='Actual Sites endpoint for review-draft only; no verification is inferred')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    try:
        if args.mcp_url and args.kind!='review-draft':raise ValueError('--mcp-url is draft-only')
        if args.kind in ('submission','review-draft'):
            config=json.loads(Path(args.production_config).read_text()) if args.production_config else {}
            if args.mcp_url:
                if args.kind!='review-draft' or 'mcp_url' in config:raise ValueError('--mcp-url is draft-only and must not override configuration')
                config['mcp_url']=args.mcp_url
            digest=(build_review_draft if args.kind=='review-draft' else build_submission)(root,args.output,config)
        else:digest=(build_local if args.kind=='local' else build_source)(root,args.output)
    except (ValueError,OSError) as e:
        print(str(e),file=sys.stderr);return 2
    result=dict(file=args.output,sha256=digest,kind=args.kind,uploaded=False,submitted=False)
    if args.kind=='review-draft':result['readiness_report']=str(Path(args.output).with_suffix('.readiness.json'))
    print(json.dumps(result))
    return 0

if __name__=='__main__':raise SystemExit(main())
