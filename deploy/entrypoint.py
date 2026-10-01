#!/usr/bin/env python3
"""Container entrypoint: use existing mounted credentials, never create them."""
import os
from pathlib import Path
import re
import stat
import sys

from rumbo.protocol import safe_json
from rumbo.__main__ import main


def load_secret_files(config):
    for key in ('introspection_secret_env','owner_client_secret_env'):
        name=config.get(key)
        if name is None:continue
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name):
            raise ValueError('Invalid secret environment reference')
        path=os.environ.get(name+'_FILE')
        if not path:continue
        if os.environ.get(name):raise ValueError('Choose a secret environment variable or mounted file, not both')
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):raise ValueError('Secret input must be a regular file')
                raw=handle.read(16385)
            if len(raw)>16384:raise ValueError('Secret input exceeds limit')
            value=raw.decode('utf-8').rstrip('\r\n')
            if not value or '\x00' in value:raise ValueError('Secret input is empty or invalid')
        except (OSError,UnicodeError):
            raise ValueError('An existing mounted secret could not be read safely') from None
        os.environ[name]=value


def port():
    value=os.environ.get('PORT','8765')
    if not value.isdigit() or not 1024<=int(value)<=65535:raise ValueError('PORT must be an unprivileged TCP port')
    return int(value)


def start():
    path=os.environ.get('RUMBO_CONFIG','/etc/rumbo/server.json')
    try:
        config=safe_json(Path(path).read_text())
        if config.get('mode')!='oauth':raise ValueError('The production container requires OAuth mode')
        if config.get('log_requests') is not True:raise ValueError('Enable privacy-safe structural request logging')
        load_secret_files(config)
        for entry in config.get('principals',[])+config.get('owner_principals',[]):
            root=Path(entry['root'])
            if not root.is_absolute() or not root.resolve().is_relative_to(Path('/var/lib/rumbo/projects')) or not root.is_dir():
                raise ValueError('Provision each persistent project root under /var/lib/rumbo/projects before startup')
        return main(['serve','--config',path,'--host','0.0.0.0','--port',str(port())])
    except (ValueError,OSError,KeyError,TypeError):
        print('Rumbo startup configuration is incomplete or unsafe; inspect approved paths and secret references. No secret values are logged.',file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(start())
