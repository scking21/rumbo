#!/usr/bin/env python3
"""Render a reviewed hostname into the proxy template. Never deploys or invents DNS."""
import argparse
from pathlib import Path
import re
import sys


def render_nginx(hostname):
    if not isinstance(hostname,str) or len(hostname)>253 or hostname!=hostname.lower():
        raise ValueError('Provide the approved lowercase public DNS hostname')
    labels=hostname.split('.')
    if len(labels)<2 or not re.fullmatch('[a-z][a-z0-9-]*',labels[-1]) or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',x) for x in labels):
        raise ValueError('Provide a well-formed public DNS hostname without URL/port')
    if labels[-1] in ('invalid','test','example','local','localhost') or any(hostname==x or hostname.endswith('.'+x) for x in ('example.com','example.net','example.org')):
        raise ValueError('Placeholder/local hostnames cannot be deployment configuration')
    return (Path(__file__).parent/'nginx.conf.template').read_text().replace('__APP_HOST__',hostname)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        rendered=render_nginx(args.hostname)
        with open(args.output,'x',encoding='utf-8') as handle:handle.write(rendered)
    except (ValueError,OSError) as error:
        print(str(error),file=sys.stderr);return 2
    print('Rendered proxy configuration only. No DNS, TLS, credentials or service was configured.')
    return 0
if __name__=='__main__':raise SystemExit(main())
