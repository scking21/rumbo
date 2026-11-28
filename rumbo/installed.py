"""Unbound, registry-selected MCP worker connection for installed plugins.

No tool or legacy environment variable can choose a path, actor, or role.
Each process owns a new worker identity; restarting never resumes old leases.
"""
import os
import sys
import uuid

from .core import RumboError, fail, fields
from .protocol import ARTIFACT, CONTRACT, TASK, Protocol, prop, rpc_error, serve_protocol_stdio, tool_definitions
from .registry import ExistingProjectEngine, ProjectRegistry


class _UnboundEngine:
    role = 'worker'

    def snapshot(self):
        fail('PROJECT_UNBOUND', 'Choose an owner-registered alias with rumbo_list_projects and rumbo_connect_project first')

    def observe_question(self, task_id, *, related_task_ids=None):
        return self.snapshot()

    def artifact_view(self, arguments):
        return self.snapshot()

    def execute(self, action, arguments):
        return self.snapshot()


def _tool(name, title, description, properties, readonly):
    return dict(name=name, title=title, description=description,
                inputSchema=dict(type='object', properties=properties, required=list(properties), additionalProperties=False),
                outputSchema=dict(type='object'),
                annotations=dict(readOnlyHint=readonly, destructiveHint=False, openWorldHint=False, idempotentHint=readonly))


SUBMISSION_INPUTS = {
    'rumbo_submit_artifact': {
        'expected_sha256': prop('string', 'SHA-256 from the file you reviewed. Supply it to prevent registering different bytes.', pattern='^[a-f0-9]{64}$'),
        'expected_artifact_revision': prop('integer', 'Previously observed artifact revision, or zero for a first registration. Prevents delayed or repeated requests from replacing newer work.', minimum=0),
    }
}


def installed_tool_definitions():
    local = [tool for tool in tool_definitions(question_observations=True) if tool['name'] != 'rumbo_submit_review']
    for tool in local:
        tool['inputSchema']['properties'].update(SUBMISSION_INPUTS.get(tool['name'], {}))
        if tool['name'] == 'rumbo_run_checks':
            tool['description'] += ' This records new evidence and can suspend acceptance and dependent work. For a read-only recheck use rumbo_verify_checks.'
        if tool['name'] == 'rumbo_submit_artifact':
            tool['description'] += ' For a reviewed file, pass its independently observed digest and prior artifact revision. On a mismatch reread the file and current task before retrying.'
    return [
        _tool('rumbo_list_projects', 'List Registered Projects', 'List only owner-provisioned project aliases available to this installed connection. Does not search the filesystem or expose project paths.', {}, True),
        _tool('rumbo_connect_project', 'Connect Registered Project', 'Bind this process once to one owner-provisioned alias as a fresh worker. Arbitrary paths, actor identities, roles, rebinding, and lease resumption are unavailable.', {'alias': prop('string', 'Owner-registered alias from rumbo_list_projects', minLength=1, maxLength=64)}, False),
        _tool('rumbo_verify_checks', 'Verify Checks Without Recording', 'Recompute deterministic criteria against the exact current registered artifact, including binary project files. Returns outcomes without appending evidence or changing human acceptance. To inspect existing evidence use rumbo_state or rumbo_read_artifact. To deliberately record new evidence use rumbo_run_checks.',
              {'task_id': TASK, 'contract_revision': CONTRACT, 'artifact_revision': ARTIFACT}, True),
    ] + local


def _verify_checks(engine, arguments):
    """Evaluate through the same preparation step used for recording, in a read transaction."""
    fields(arguments, {'task_id', 'contract_revision', 'artifact_revision'})
    with engine._db() as db:
        db.execute('BEGIN')
        now = engine._now()
        state = engine._project(engine._replay(db), now)
        prepared = engine._prepare('run_checks', arguments, state, now)
        task = engine._task(arguments['task_id'], state)
        artifact = task['artifact']
        # Preparation computes deterministic outcomes. Only execute() can append the receipts.
        checks = [{key: row[key] for key in ('check_id', 'outcome', 'detail')}
                  for row in prepared['evidence']]
        return dict(project_id=state['project_id'], task_id=task['id'], contract_revision=state['contract_revision'],
                    artifact_revision=artifact['revision'], sha256=artifact['sha256'], ledger_head=state['ledger_head'],
                    status=task['status'], recorded=False, checks=checks,
                    manual_review_ids=[c['id'] for c in task['acceptance'] if c['kind'] == 'manual_review'],
                    notice='Computed the listed deterministic checks for this observation. Manual criteria were not evaluated. '
                           'Status is the projected ledger status at observation time. No receipt or decision was recorded.')


def _success(data, text):
    return dict(content=[dict(type='text', text=text)], structuredContent=data, isError=False)


def _failure(error):
    return dict(content=[dict(type='text', text=str(error))], isError=True)


class InstalledProtocol(Protocol):
    extra_tool_inputs = SUBMISSION_INPUTS

    def __init__(self, plugin_data, clock=None):
        self.registry = ProjectRegistry(plugin_data)
        self.actor = 'worker-' + uuid.uuid4().hex
        self.alias = None
        self.clock = clock
        super().__init__(_UnboundEngine(), question_observations=True)

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
            if name == 'rumbo_verify_checks':
                try:
                    if self.alias is None:
                        self.engine.snapshot()  # Emits the same PROJECT_UNBOUND diagnostic as the other reads.
                    observation = _verify_checks(self.engine, params.get('arguments', {}))
                    result = _success(observation, observation['notice'])
                except RumboError as error:
                    reasons = {
                        'ARTIFACT_CHANGED': 'The bytes differ from the registered digest.',
                        'STALE_ARTIFACT': 'The requested artifact revision is unavailable under the current task definition.',
                        'STALE_CONTRACT': 'The requested contract revision is no longer current.',
                        'DEPENDENCY_BLOCKED': 'A prerequisite is unaccepted or its approved basis has changed.',
                    }
                    if error.code in reasons:
                        message = reasons[error.code] + ' Read current state and report the mismatch for this request; changing registrations or evidence requires a separate decision.'
                        result = _failure(RumboError(error.code, message))
                        result['structuredContent'] = dict(code=error.code, recorded=False,
                                                           recovery=dict(tool='rumbo_state', arguments={}))
                    else:
                        result = _failure(error)
                except (OSError, ValueError, TypeError, RecursionError):
                    return rpc_error(request['id'], -32603, 'Local verification failed; inspect the project and its ledger')
                return dict(jsonrpc='2.0', id=request['id'], result=result)
            if name == 'rumbo_submit_review':
                return rpc_error(request['id'], -32602, 'Unknown tool')
            if name in ('rumbo_list_projects', 'rumbo_connect_project'):
                try:
                    args = params.get('arguments', {})
                    fields(args, {'alias'} if name == 'rumbo_connect_project' else set())
                    if name == 'rumbo_list_projects':
                        projects = self.registry.list_projects()
                        guide = ('This process selected alias ' + self.alias + '. Call rumbo_state to verify current access and read its contract.'
                                 if self.alias is not None else 'Connect one owner-registered alias before using project tools.')
                        result = _success(dict(projects=projects, bound_alias=self.alias), guide)
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
