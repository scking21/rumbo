#!/usr/bin/env python3
"""Installed worker-only launcher with process-local approval preservation."""
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rumbo.core import RumboError
from rumbo.installed import InstalledProtocol
from rumbo.protocol import Protocol, prop, serve_protocol_stdio


PRESERVE = 'preserve_approval'
OVERRIDE = 'record_after_verification'
VERIFY = 'rumbo_verify_checks'
RECORD = 'rumbo_run_checks'
PROTECTED = 'APPROVAL_PRESERVED'


def rejection(request_id, code, message):
    return dict(jsonrpc='2.0', id=request_id, result=dict(isError=True,
        content=[dict(type='text', text=code + ': ' + message)],
        structuredContent=dict(code=code, recorded=False, recovery=dict(tool='rumbo_state', arguments={}))))


class _OneUseCheckRecorder:
    """One authorized run_checks call, entered only after the shared protocol validates it."""

    role = 'worker'

    def __init__(self, engine, protected, target):
        self.engine = engine
        self.protected = protected
        self.target = target

    def execute(self, action, arguments):
        if action != 'run_checks':
            raise ValueError('Expected a check recording')
        # The engine may commit before a reply arrives. Never restore a spent observation.
        self.protected[self.target] = None
        return self.engine.execute(action, arguments)


class ApprovalProtocol(InstalledProtocol):
    def __init__(self, plugin_data):
        super().__init__(plugin_data)
        # Entries belong to this single bound worker. None means the one-use override was spent.
        self.protected = {}

    def dispatch(self, request):
        if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
                or type(request.get('id')) not in (int, str)):
            return super().dispatch(request)
        if request.get('method') == 'tools/list':
            response = super().dispatch(request)
            for tool in response.get('result', {}).get('tools', []):
                properties = tool['inputSchema']['properties']
                if tool['name'] == VERIFY:
                    properties[PRESERVE] = prop('boolean', 'Set true when rechecking while retaining current acceptance. Protects this approved task and exact revisions from inadvertent check recording on this connection only. Other tasks can still record.')
                if tool['name'] == RECORD:
                    properties[OVERRIDE] = prop('string', 'One-use override from a protected verification of these exact revisions. Use only when new evidence on this target was explicitly requested. After an uncertain delivery read current state first.')
            return response

        params = request.get('params')
        if (request.get('method') != 'tools/call' or not isinstance(params, dict)
                or set(params) - {'name', 'arguments', '_meta'}):
            return super().dispatch(request)
        name = params.get('name')
        args = params.get('arguments')
        if name not in (VERIFY, RECORD) or not isinstance(args, dict):
            return super().dispatch(request)
        if name == VERIFY and PRESERVE not in args:
            return super().dispatch(request)

        # Validate identity before indexing connection state. Leave ordinary malformed calls
        # to the stock validator, including notifications, missing revisions and unbound calls.
        target = (args.get('task_id'), args.get('contract_revision'), args.get('artifact_revision'))
        if (type(target[0]) is not str or type(target[1]) is not int or type(target[2]) is not int
                or self.alias is None):
            return super().dispatch(request)

        if name == VERIFY:
            if type(args[PRESERVE]) is not bool:
                return rejection(request['id'], 'BAD_INPUT', PRESERVE + ' must be boolean')
            clean_args = {key:value for key,value in args.items() if key != PRESERVE}
            response = super().dispatch(dict(request, params=dict(params, arguments=clean_args)))
            result = response.get('result', {})
            if args[PRESERVE] and result.get('isError') is False:
                data = result['structuredContent']
                if data['status'] == 'accepted' or target in self.protected:
                    token = uuid.uuid4().hex
                    self.protected[target] = token
                    data['approval_preservation'] = dict(active=True, scope='connection_and_exact_revisions',
                        record_after_verification=token)
                    result['content'][0]['text'] += ' Check recording is held for these revisions on this connection.'
                else:
                    data['approval_preservation'] = dict(active=False, reason='No current acceptance to preserve')
            return response

        if target not in self.protected and OVERRIDE not in args:
            return super().dispatch(request)
        try:
            self.engine.verify()
        except RumboError as error:
            return rejection(request['id'], error.code, error.message)
        token = self.protected.get(target)
        if not token or args.get(OVERRIDE) != token:
            return rejection(request['id'], PROTECTED,
                'No new evidence recorded. Use the verification for the handoff and continue other authorized tasks. '
                'If new receipts for these exact revisions were requested, verify with preserve_approval=true '
                'and supply that observation\'s one-use record_after_verification.')
        clean_args = {key:value for key,value in args.items() if key != OVERRIDE}
        # Use the same protocol validation and receipt formatting as ordinary check recording.
        # A transport option rejected before execute() leaves this exact observation available.
        recorder = _OneUseCheckRecorder(self.engine, self.protected, target)
        return Protocol(recorder).dispatch(dict(request, params=dict(params, arguments=clean_args)))


def main():
    plugin_data = os.environ.get('PLUGIN_DATA')
    if not plugin_data:
        print('PLUGIN_DATA must identify the host-provided private plugin data directory. Ask the owner to register initialized project aliases; no legacy project or role environment fallback is supported.', file=sys.stderr)
        return 2
    try:
        serve_protocol_stdio(ApprovalProtocol(plugin_data))
        return 0
    except (RumboError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
