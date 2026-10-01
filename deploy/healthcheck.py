#!/usr/bin/env python3
"""Local container readiness, no issuer call or authentication data."""
import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def port():
    value=os.environ.get('PORT','8765')
    if not value.isdigit() or not 1024<=int(value)<=65535:raise ValueError('PORT must be an unprivileged TCP port')
    return int(value)


def check(config_path):
    connection=None
    try:
        config=json.loads(Path(config_path).read_text())
        host=urlsplit(config['public_url']).netloc
        if not host:return False
        connection=http.client.HTTPConnection('127.0.0.1',port(),timeout=4)
        connection.request('GET','/health/ready',headers={'Host':host})
        response=connection.getresponse()
        return response.status==200 and json.loads(response.read())=={'status':'ok'}
    except (OSError,ValueError,KeyError,http.client.HTTPException):return False
    finally:
        if connection:connection.close()

if __name__=='__main__':raise SystemExit(0 if check(os.environ.get('RUMBO_CONFIG','/etc/rumbo/server.json')) else 1)
