"""Unbound, registry-selected MCP worker connection for installed plugins.

No tool or legacy environment variable can choose a path, actor, or role.
Each process owns a new worker identity; restarting never resumes old leases.
"""
import os
import sys
import uuid

from .core import RumboError, fail, fields
from .protocol import Protocol, prop, rpc_error, serve_protocol_stdio, tool_definitions
from .registry import ExistingProjectEngine, ProjectRegistry


class _UnboundEngine:
    role = 'worker'

    def snapshot(self):
        fail('PROJECT_UNBOUND', 'Choose an owner-registered alias with rumbo_list_projects and rumbo_connect_project first')

    def artifact_view(self, arguments):
        return self.snapshot()

    def execute(self, action, arguments):
        return self.snapshot()


def _tool(name, title, description, properties, readonly):
    return dict(name=name, title=title, description=description,
                inputSchema=dict(type='object', properties=properties, required=list(properties), additionalProperties=False),
                outputSchema=dict(type='object'),
                annotations=dict(readOnlyHint=readonly, destructiveHint=False, openWorldHint=False, idempotentHint=readonly))


def installed_tool_definitions():
    return [
        _tool('rumbo_list_projects', 'List Registered Projects', 'List only owner-provisioned project aliases available to this installed connection. Does not search the filesystem or expose project paths.', {}, True),
        _tool('rumbo_connect_project', 'Connect Registered Project', 'Bind this process once to one owner-provisioned alias as a fresh worker. Arbitrary paths, actor identities, roles, rebinding, and lease resumption are unavailable.', {'alias': prop('string', 'Owner-registered alias from rumbo_list_projects', minLength=1, maxLength=64)}, False),
    ] + [tool for tool in tool_definitions() if tool['name'] != 'rumbo_submit_review']


def _success(data, text):
    return dict(content=[dict(type='text', text=text)], structuredContent=data, isError=False)


def _failure(error):
    return dict(content=[dict(type='text', text=str(error))], isError=True)


class InstalledProtocol(Protocol):
    def __init__(self, plugin_data, clock=None):
        self.registry = ProjectRegistry(plugin_data)
        self.actor = 'worker-' + uuid.uuid4().hex
        self.alias = None
        self.clock = clock
        super().__init__(_UnboundEngine())

    def dispatch(self, request):
        # Keep the shared protocol's validation and notification behavior. In
        # particular, notifications must never bind a project or mutate state.
        if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
                or not isinstance(request.get('method'), str)
                or 'id' not in request or type(request['id']) not in (str, int)
                or not isinstance(request.get('params', {}), dict)):
            return super().dispatch(request)
        method = request['method']
        if method == 'tools/list':
            return dict(jsonrpc='2.0', id=request['id'], result=dict(tools=installed_tool_definitions()))
        if method == 'tools/call':
            params = request.get('params', {})
            try:
                fields(params, {'name'}, {'arguments', '_meta'})
            except RumboError as error:
                return rpc_error(request['id'], -32602, str(error))
            name = params['name']
            if name == 'rumbo_submit_review':
                return rpc_error(request['id'], -32602, 'Unknown tool')
            if name in ('rumbo_list_projects', 'rumbo_connect_project'):
                try:
                    args = params.get('arguments', {})
                    fields(args, {'alias'} if name == 'rumbo_connect_project' else set())
                    if name == 'rumbo_list_projects':
                        projects = self.registry.list_projects()
                        result = _success(dict(projects=projects), str(len(projects)) + ' owner-registered projects. Connect one alias before using project tools.')
                    else:
                        if self.alias is not None:
                            fail('PROJECT_ALREADY_BOUND', 'This process is already bound; start a new connection to select another project')
                        entry = self.registry.resolve(args['alias'])
                        engine = ExistingProjectEngine(entry['root'], self.actor, expected=entry, guard=self.registry.verify, clock=self.clock)
                        self.engine = engine
                        self.alias = args['alias']
                        result = _success(dict(alias=self.alias, project_id=engine.project_id, contract_revision=engine.contract_revision, actor=self.actor, role='worker'),
                                          'Connected ' + self.alias + ' as a new worker. Leases expire after 30 to 3600 seconds; restarting does not resume them. Reviewer and human authority are unavailable here.')
                except RumboError as error:
                    result = _failure(error)
                except (OSError, ValueError, TypeError, RecursionError):
                    return rpc_error(request['id'], -32603, 'Installed operation failed; ask the owner to inspect the registry and initialized project')
                return dict(jsonrpc='2.0', id=request['id'], result=result)
        response = super().dispatch(request)
        if method == 'initialize' and response and 'result' in response:
            response['result']['instructions'] += ' Installed connections begin unbound. Use only owner-registered aliases; each process binds once as a fresh worker. Reviewer workflow requires a separately authorized connection.'
        return response


def main():
    plugin_data = os.environ.get('PLUGIN_DATA')
    if not plugin_data:
        print('PLUGIN_DATA must identify the host-provided private plugin data directory. Ask the owner to register initialized project aliases; no legacy project or role environment fallback is supported.', file=sys.stderr)
        return 2
    try:
        serve_protocol_stdio(InstalledProtocol(plugin_data))
        return 0
    except (RumboError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
