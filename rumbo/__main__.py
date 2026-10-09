"""Local operator CLI and agent-safe transports. Run python -m rumbo --help."""
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .core import Engine, RumboError
from .protocol import safe_json, serve_stdio
from .server import create_server


def _json(text,source):
    try:return safe_json(text)
    except (ValueError,RecursionError) as e:
        raise RumboError('BAD_INPUT',source+' is not one valid JSON value: '+str(e))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Rumbo local contract and evidence referee')
    parser.add_argument('--version',action='version',version='rumbo '+__version__)
    parser.add_argument('--root',default='.',help='Trusted project root (not a tool argument)')
    parser.add_argument('--actor',default='local-worker',help='Local host principal identity')
    parser.add_argument('--role',choices=['worker','reviewer','viewer'],default='worker')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('state',help='Read project state and hash-chain integrity')
    sub.add_parser('verify',help='Read-only verification of an existing event chain and its current checkpoint')
    call=sub.add_parser('call',help='Invoke an agent-safe action with a JSON object')
    call.add_argument('action',choices=['claim_task','submit_artifact','ingest_artifact','run_checks','submit_review','request_decision']);call.add_argument('--json',required=True)
    operator=sub.add_parser('operator',help='Trusted local human operator flow; interactive confirmation required')
    operator.add_argument('action',choices=['create_contract','revise_contract','decide']);operator.add_argument('--file',required=True);operator.add_argument('--owner',required=True)
    sub.add_parser('mcp',help='MCP stdio server, no human-authority tools')
    serve=sub.add_parser('serve',help='Run Streamable HTTP behind your approved TLS/OAuth deployment')
    serve.add_argument('--config',required=True);serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',type=int,default=8765)
    sub.add_parser('demo',help='Create an isolated synthetic sample project; refuses existing contract')
    args=parser.parse_args(argv)
    try:
        if args.command=='serve':
            config=safe_json(Path(args.config).read_text())
            server=create_server(args.host,args.port,config)
            print('Rumbo HTTP listening on '+args.host+':'+str(server.server_port),file=sys.stderr)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:server.server_close()
            return 0
        if args.command=='demo':
            from .demo import create_demo
            result=create_demo(args.root)
        elif args.command=='operator':
            if not sys.stdin.isatty():
                raise RumboError('HUMAN_CONFIRMATION_REQUIRED','Noninteractive invocation refused; use the trusted local operator flow. A terminal is not proof of human identity')
            payload=_json(Path(args.file).read_text(),args.file)
            print(json.dumps(payload,indent=2,ensure_ascii=False))
            phrase='CONFIRM '+args.action
            if input('As the human decision owner, type '+phrase+': ')!=phrase:
                raise RumboError('CANCELLED')
            result=Engine(args.root,args.owner,'human').execute(args.action,payload)
        else:
            # Only the owner's create_contract or demo may start a ledger; a mistyped --root must not leave one behind.
            if args.command!='verify' and Path(args.root).is_dir() and not (Path(args.root)/'.rumbo'/'state.sqlite3').is_file():
                raise RumboError('NO_CONTRACT','No Rumbo project in '+str(Path(args.root).resolve())+'; check --root, or have the owner run operator create_contract there')
            engine=Engine(args.root,args.actor,'viewer' if args.command=='verify' else args.role,read_only=args.command=='verify')
            if args.command=='mcp':
                serve_stdio(engine);return 0
            if args.command=='call':
                result=engine.execute(args.action,_json(args.json,'--json'))
            else:
                result=engine.checkpoint() if args.command=='verify' else engine.snapshot()
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
        return 0
    except (RumboError,OSError,ValueError,RecursionError) as e:
        print(str(e),file=sys.stderr);return 2


if __name__=='__main__':
    raise SystemExit(main())
