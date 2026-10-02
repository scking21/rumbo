#!/usr/bin/env python3
"""Reproducible local release or guarded public review archive. Never uploads."""
import argparse
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import zipfile

STAMP=(2026,10,1,0,0,0)
PUBLIC_FIELDS={'mcp_url','website_url','support_url','privacy_url','terms_url','video_url','attestations'}
GATES={'https_endpoint_verified','oauth_verified','domain_verified','publisher_verified','reviewer_account_verified','host_qa_verified','legal_pages_reviewed','video_access_verified'}


def validate_public_config(config):
    if not isinstance(config,dict) or set(config)!=PUBLIC_FIELDS:
        raise ValueError('Public package blocked: provide all production URLs and verification attestations; see docs/DEPLOYMENT.md')
    for name in PUBLIC_FIELDS-{'attestations'}:
        value=config[name]
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
    attestations=config['attestations']
    if not isinstance(attestations,dict) or set(attestations)!=GATES or any(v is not True for v in attestations.values()):
        raise ValueError('Public package blocked: every documented external verification gate must be completed, not assumed')


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


def build_source(root,target):
    root=Path(root);files={}
    for name in ['README.md','LICENSE','PRIVACY.md','SECURITY.md','pyproject.toml','requirements-owner.txt','requirements-authkit.txt','.gitignore','.dockerignore']:
        if (root/name).is_file():files[name]=(root/name).read_bytes()
    for dirname in ['rumbo','claude-plugin','tests','scripts','schemas','openai-plugin','docs','deploy','.github','.claude-plugin']:
        for path in (root/dirname).rglob('*'):
            relative=path.relative_to(root).as_posix()
            if path.is_symlink():raise ValueError('Symlink packaging forbidden')
            parts=path.relative_to(root).parts
            if any(part.lower() in {'.env','credentials.json','secrets.json','.netrc','.npmrc','.pypirc','.aws','.ssh','.gnupg'} or part.lower().startswith('.env.') for part in parts):
                raise ValueError('Potential credential input is forbidden in source packages: '+relative)
            if path.is_file() and not any(part in ('__pycache__','.rumbo','superpowers') for part in path.parts) and path.suffix.lower() not in ('.pyc','.sqlite3','.sqlite','.db','.zip','.tar','.gz','.pem','.key'):
                if dirname=='deploy' and path.relative_to(root/'deploy').as_posix() not in {'Dockerfile','compose.yml','nginx.conf.template','render.py','entrypoint.py','healthcheck.py','server-config.template.json','ci_smoke.py','render.yaml.template'}:
                    raise ValueError('Unexpected deployment input; never package live configuration or credentials: '+relative)
                files[relative]=path.read_bytes()
    return write_zip(target,files,prefix='rumbo-0.3.0-source')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=['local','source','submission'],default='local');p.add_argument('--output',required=True);p.add_argument('--production-config')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    try:
        if args.kind=='submission':
            config=json.loads(Path(args.production_config).read_text()) if args.production_config else {}
            digest=build_submission(root,args.output,config)
        else:digest=(build_local if args.kind=='local' else build_source)(root,args.output)
    except (ValueError,OSError) as e:
        print(str(e),file=sys.stderr);return 2
    print(json.dumps(dict(file=args.output,sha256=digest,kind=args.kind,uploaded=False,submitted=False)))
    return 0

if __name__=='__main__':raise SystemExit(main())
