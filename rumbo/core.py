"""Deterministic event-sourced referee. Host principals, never tool arguments, own roles.

This is an integrity aid within one trusted operating-system account, not a
sandbox against an actor who can rewrite the database, executable or project.
"""
import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

MAX_ARTIFACT = 5 * 1024 * 1024
MAX_INGEST = 128 * 1024
MAX_UPLOAD_TOTAL = 64 * 1024 * 1024
MAX_EVENTS = 10000
MAX_LEDGER_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_JSON_DEPTH = 512
MAX_ARTIFACT_JSON_INTEGER_DIGITS = 4300
ROLES = {'human', 'worker', 'reviewer', 'viewer'}
REVISION_SCOPES = ('contract', 'task')
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
ACTION_FIELDS = {
    'create_contract': ({'project_id','goal','original_request','decision_owner','constraints','tasks'}, {'demo','revision_scope'}),
    'revise_contract': ({'contract','expected_revision','reason'}, set()),
    'claim_task': ({'task_id','contract_revision','lease_seconds'}, set()),
    'submit_artifact': ({'task_id','contract_revision','path'}, {'expected_sha256','expected_artifact_revision'}),
    'ingest_artifact': ({'task_id','contract_revision','filename','content'}, {'expected_sha256','expected_artifact_revision'}),
    'run_checks': ({'task_id','contract_revision','artifact_revision'}, set()),
    'submit_review': ({'task_id','contract_revision','artifact_revision','check_id','outcome','detail'}, set()),
    'request_decision': ({'task_id','question'}, {'observation', 'request_key'}),
    'decide': ({'task_id','contract_revision','artifact_revision','outcome','reason'}, {'expected_review_basis'}),
}


class RumboError(Exception):
    def __init__(self, code, message=''):
        self.code = code
        self.message = message or code.replace('_', ' ').lower()
        super().__init__(code + ': ' + self.message)


def fail(code, message=''):
    raise RumboError(code, message)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        fail('BAD_INPUT', 'Use finite, JSON-compatible values')


def artifact_json(raw):
    """Decode artifact JSON with stable limits independent of transport policy.

    Preserve byte-encoding detection and last-key-wins for scalar strings.
    Nonfinite values cannot themselves become passing canonical evidence.
    """
    text = raw.decode(json.detect_encoding(raw), 'strict')
    depth = 0
    quoted = escaped = False
    token_start = 0
    for offset, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
                token = text[token_start:offset+1]
                # Strict byte decoding already excludes literal surrogates.
                # Validate escaped strings before duplicate keys discard values.
                if '\\u' in token and any(0xD800 <= ord(value) <= 0xDFFF for value in json.loads(token)):
                    raise ValueError('Artifact JSON strings must be Unicode scalars')
        elif char == '"':
            quoted = True
            token_start = offset
        elif char in '[{':
            depth += 1
            if depth > MAX_ARTIFACT_JSON_DEPTH:
                raise ValueError('Artifact JSON nesting exceeds limit')
        elif char in ']}':
            depth -= 1

    def parse_integer(token):
        negative = token.startswith('-')
        digits = token[1:] if negative else token
        if len(digits) > MAX_ARTIFACT_JSON_INTEGER_DIGITS:
            raise ValueError('Artifact JSON integer exceeds digit limit')
        # Chunk conversion avoids interpreter-global integer-string settings.
        value = 0
        for start in range(0, len(digits), 500):
            chunk = digits[start:start+500]
            value = value * (10 ** len(chunk)) + int(chunk)
        return -value if negative else value

    return json.loads(text, parse_int=parse_integer)


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        fail('BAD_INPUT', 'Expected an object')
    unknown = set(value) - set(required) - set(optional)
    if unknown:
        fail('UNKNOWN_FIELD', ', '.join(sorted(unknown)))
    if set(required) - set(value):
        fail('MISSING_FIELD', ', '.join(sorted(set(required) - set(value))))


def string(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        fail('BAD_INPUT', name + ' must be nonempty text (max ' + str(limit) + ')')
    return value


def identifier(value, name):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail('BAD_INPUT', 'Invalid ' + name)
    return value


def integer(value, name, minimum=1, maximum=1000000000):
    if type(value) is not int or not minimum <= value <= maximum:
        fail('BAD_INPUT', name + ' is outside its integer range')
    return value


def task_fingerprint(state, task):
    """Identity of what was agreed for one task: its definition plus the shared goal and constraints.

    Under revision_scope "task", only a change to this fingerprint makes the task's work stale.
    """
    material = dict(goal=state['goal'], constraints=state['constraints'],
                    task={key: task[key] for key in ('id', 'title', 'dependencies', 'acceptance')})
    return hashlib.sha256(canonical(material).encode()).hexdigest()


def binder(task, state):
    """Return a test for whether an artifact, evidence item or decision still belongs to the task as now agreed.

    The task's fingerprint is computed once here, so testing a long history stays cheap.
    """
    if state.get('revision_scope') == 'task':
        current = task_fingerprint(state, task)
        return lambda item: item.get('task_fingerprint') == current
    revision = state['contract_revision']
    return lambda item: item['contract_revision'] == revision


def project_file_path(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 512 or '\\' in relative or '\x00' in relative:
        fail('PATH_INVALID', 'Use a project-relative file path of at most 512 characters with forward slashes')
    while relative.startswith('./'):
        relative = relative[2:]
    path = Path(relative)
    if not path.parts or path.is_absolute() or any(p in ('.','..') for p in relative.split('/')):
        fail('PATH_INVALID', 'Use a project-relative file path without traversal')
    forbidden = {'.git','.rumbo','.ssh','.aws','.codex','.agents','.docker','.kube','.config','.gcloud','.azure','.gnupg','.password-store','.npmrc','.pypirc','.netrc','.git-credentials','.gitconfig','.yarnrc','.yarnrc.yml','id_rsa','id_ed25519','node_modules','__pycache__'}
    for part in path.parts:
        folded = part.casefold()
        if folded in forbidden or folded == '.env' or folded.startswith('.env.') or folded.endswith(('.pem','.key','.p12','.pfx')):
            fail('PATH_PRIVATE', 'Private/configuration paths cannot be artifacts')
    return path


def validate_contract(data, actor):
    fields(data, *ACTION_FIELDS['create_contract'])
    identifier(data['project_id'], 'project_id')
    string(data['goal'], 'goal'); string(data['original_request'], 'original_request', 16000)
    identifier(data['decision_owner'], 'decision_owner')
    if data['decision_owner'] != actor:
        fail('FORBIDDEN', 'The authenticated decision owner must own the contract')
    if 'demo' in data and type(data['demo']) is not bool:
        fail('BAD_INPUT', 'demo must be boolean')
    if 'revision_scope' in data and data['revision_scope'] not in REVISION_SCOPES:
        fail('BAD_INPUT', 'revision_scope must be contract or task')
    if not isinstance(data['constraints'], list) or len(data['constraints']) > 50:
        fail('BAD_INPUT', 'constraints must be an array of at most 50 strings')
    for value in data['constraints']:
        string(value, 'constraint')
    tasks = data['tasks']
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 100:
        fail('BAD_INPUT', 'Include 1 to 100 bounded tasks')
    ids = set()
    for task in tasks:
        fields(task, {'id','title','dependencies','acceptance'})
        identifier(task['id'], 'task id'); string(task['title'], 'task title')
        if task['id'] in ids:
            fail('BAD_INPUT', 'Duplicate task id')
        ids.add(task['id'])
        if not isinstance(task['dependencies'], list) or len(task['dependencies']) > 100:
            fail('BAD_INPUT', 'Invalid dependencies')
        for dep in task['dependencies']:
            identifier(dep, 'dependency')
        if len(set(task['dependencies'])) != len(task['dependencies']):
            fail('BAD_INPUT', 'Duplicate dependency')
        checks = task['acceptance']
        if not isinstance(checks, list) or not 1 <= len(checks) <= 30:
            fail('BAD_INPUT', 'Include 1 to 30 acceptance checks')
        seen = set()
        destination = None
        for check in checks:
            if not isinstance(check, dict):
                fail('BAD_INPUT', 'Acceptance must contain objects')
            kind = check.get('kind')
            required = {'id','kind'}
            extras = {'project_file_at': {'value'}, 'file_contains': {'value'}, 'json_equals': {'key','value'}, 'sha256': {'value'}, 'manual_review': {'prompt'}}
            if not isinstance(kind, str) or kind not in extras:
                fail('BAD_INPUT', 'Unsupported check kind')
            fields(check, required | extras[kind])
            identifier(check['id'], 'check id')
            if check['id'] in seen:
                fail('BAD_INPUT', 'Duplicate check id')
            seen.add(check['id'])
            if kind in ('file_contains', 'sha256'):
                string(check['value'], 'check value', 16000)
            if kind == 'project_file_at':
                expected_path = project_file_path(check['value'])
                if destination is not None and destination != expected_path:
                    fail('BAD_INPUT', 'One registered artifact cannot occupy two different required destinations')
                destination = expected_path
            if kind == 'sha256' and not re.fullmatch(r'[a-f0-9]{64}', check['value']):
                fail('BAD_INPUT', 'sha256 must be a lowercase digest')
            if kind == 'json_equals':
                string(check['key'], 'JSON top-level key', 256)
                if len(canonical(check['value'])) > 16000:
                    fail('BAD_INPUT', 'JSON expected value too large')
            if kind == 'manual_review':
                string(check['prompt'], 'review prompt')
    by_id = {t['id']: t for t in tasks}
    visiting, visited = set(), set()
    def visit(tid):
        if tid not in ids:
            fail('BAD_INPUT', 'Unknown dependency')
        if tid in visiting:
            fail('DEPENDENCY_CYCLE', 'Task dependencies form a cycle through ' + tid)
        if tid in visited:
            return
        visiting.add(tid)
        for dep in by_id[tid]['dependencies']:
            visit(dep)
        visiting.remove(tid); visited.add(tid)
    for task in tasks:
        visit(task['id'])
    if len(canonical(data).encode()) > 256000:
        fail('BAD_INPUT', 'Contract too large')


class Engine:
    def __init__(self, root, actor, role, clock=None, read_only=False, create=True):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            fail('PATH_INVALID', 'Project root must exist')
        self.actor = identifier(actor, 'host actor')
        if role not in ROLES:
            fail('FORBIDDEN', 'Unknown host role')
        if type(read_only) is not bool:
            fail('BAD_INPUT', 'read_only must be boolean')
        if read_only and role != 'viewer':
            fail('FORBIDDEN', 'Read-only storage requires a viewer principal')
        self.role = role
        self.read_only = read_only
        self.create = create
        self.clock = clock or time.time
        state = self.root / '.rumbo'
        if state.is_symlink():
            fail('PATH_UNSAFE', 'State directory may not be a symlink')
        # Only a caller that may start a project creates storage; a lost or mistyped root must not gain an empty ledger.
        existing = read_only or not create
        if existing:
            if not state.is_dir():
                fail('NO_CONTRACT', 'No project ledger in this root; check the root, or have its owner initialize a contract first')
        else:
            state.mkdir(mode=0o700, exist_ok=True)
        self.db_path = state / 'state.sqlite3'
        if self.db_path.is_symlink():
            fail('PATH_UNSAFE', 'State database may not be a symlink')
        if existing:
            if not self.db_path.is_file():
                fail('NO_CONTRACT', 'No project ledger in this root; check the root, or have its owner initialize a contract first')
        else:
            with self._db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL)')
            os.chmod(self.db_path, 0o600)

    @contextmanager
    def _db(self):
        db=None
        try:
            if self.read_only:
                db=sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True,timeout=15)
                db.execute('PRAGMA query_only=ON')
            elif self.create:
                db=sqlite3.connect(str(self.db_path),timeout=15)
            else:
                # mode=rw never creates a database that vanished after construction.
                db=sqlite3.connect(self.db_path.as_uri()+'?mode=rw',uri=True,timeout=15)
            db.execute('PRAGMA busy_timeout=15000')
            with db:
                yield db
        except sqlite3.DatabaseError:
            fail('LEDGER_UNREADABLE','Database operation failed; inspect storage and restore from a trusted backup if needed')
        finally:
            if db is not None:db.close()

    def _replay(self, db):
        state = dict(version=1, project_id=None, goal='', original_request='', decision_owner='', contract_revision=0, constraints=[], tasks=[], requests=[], demo=False, events_count=0, ledger_head='0'*64, integrity={'valid': True})
        rows = db.execute('SELECT seq,payload,previous,digest FROM events ORDER BY seq').fetchall()
        if len(rows) > MAX_EVENTS:
            fail('LEDGER_LIMIT', 'Ledger exceeds ' + str(MAX_EVENTS) + ' events; ask its owner to archive the project and start a new one')
        previous = '0'*64
        for expected, (seq, raw, prev, digest) in enumerate(rows, 1):
            if seq != expected or prev != previous or hashlib.sha256((prev+'\n'+raw).encode()).hexdigest() != digest:
                fail('LEDGER_CORRUPT', 'Hash-chain verification failed; restore from a trusted copy')
            try:
                event = json.loads(raw)
                self._apply(state, event)
            except (ValueError, KeyError, TypeError, IndexError):
                fail('LEDGER_CORRUPT', 'Invalid ledger event')
            previous = digest
        state['events_count'] = len(rows); state['ledger_head'] = previous
        return state

    def _apply(self, state, event):
        action, data = event['action'], event['data']
        if action in ('create_contract', 'revise_contract'):
            prior = {t['id']: t for t in state['tasks']}
            state.update(copy.deepcopy(data))
            if 'revision_scope' not in data:
                state.pop('revision_scope', None)
            tasks = []
            for item in data['tasks']:
                task = copy.deepcopy(item)
                old = prior.get(task['id'], {})
                task.update(contract_revision=data['contract_revision'], lease=None, artifact=old.get('artifact'), evidence=old.get('evidence', []), decisions=old.get('decisions', []))
                tasks.append(task)
            state['tasks'] = tasks
        elif action == 'request_decision':
            state['requests'].append(data)
        else:
            task = next(t for t in state['tasks'] if t['id'] == data['task_id'])
            if action == 'claim_task':
                task['lease'] = data['lease']
            elif action in ('submit_artifact','ingest_artifact'):
                task['artifact'] = data['artifact']
            elif action in ('run_checks', 'submit_review'):
                task['evidence'].extend(data['evidence'])
            elif action == 'decide':
                task['decisions'].append(data['decision'])
            else:
                raise ValueError('Unknown ledger action')

    def _artifact_bytes(self, relative):
        path = project_file_path(relative)
        candidate = self.root / path
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                fail('PATH_UNSAFE', 'Symlink artifacts are not supported')
        try:
            if not candidate.resolve().is_relative_to(self.root):
                fail('PATH_UNSAFE', 'Artifact path resolves outside the project root')
            # Open directory components without following symlinks to close check/open races.
            fd = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in path.parts[:-1]:
                    new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd); fd = new
                filefd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(filefd, 'rb') as handle:
                    import stat
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        fail('PATH_INVALID', 'Artifact must be a regular file')
                    data = handle.read(MAX_ARTIFACT+1)
            finally:
                os.close(fd)
        except OSError:
            fail('PATH_UNREADABLE', 'Artifact not readable inside the project')
        if len(data) > MAX_ARTIFACT:
            fail('PATH_TOO_LARGE', 'Artifacts are limited to 5 MiB')
        return data

    def _digest(self, path):
        data = self._artifact_bytes(path)
        return hashlib.sha256(data).hexdigest(), len(data), data

    def _upload_dir(self,create=False):
        try:
            statefd=os.open(str(self.root/'.rumbo'),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                if create:
                    try:
                        os.mkdir('artifacts',mode=0o700,dir_fd=statefd)
                        os.fsync(statefd)
                    except FileExistsError:pass
                return os.open('artifacts',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=statefd)
            finally:os.close(statefd)
        except OSError:
            fail('PATH_UNSAFE','Uploaded artifact storage is unavailable or unsafe')

    def _store_upload(self,digest,data):
        """Publish complete blobs only, while execute holds the SQLite write lock."""
        import stat
        fd=self._upload_dir(create=True)
        staging='.upload-'+digest+'.tmp'
        staged=False
        try:
            # No other supported writer can own staging while we hold the lock.
            # Reclaim only our reserved regular staging files after abrupt exits.
            cleaned=False
            for name in os.listdir(fd):
                if re.fullmatch(r'\.upload-[a-f0-9]{64}\.tmp',name):
                    info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        fail('PATH_UNSAFE','Unsafe upload staging file')
                    os.unlink(name,dir_fd=fd)
                    cleaned=True
            if cleaned:os.fsync(fd)
            try:
                existing=os.open(digest,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            except FileNotFoundError:
                existing=None
            if existing is not None:
                with os.fdopen(existing,'rb') as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or handle.read(MAX_INGEST+1)!=data:
                        fail('ARTIFACT_CORRUPT','Existing uploaded digest path does not match its bytes')
                os.fsync(fd)
                return
            total=0
            for name in os.listdir(fd):
                info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if not re.fullmatch(r'[a-f0-9]{64}',name) or not stat.S_ISREG(info.st_mode):
                    fail('PATH_UNSAFE','Unexpected content in upload storage')
                total+=info.st_size
            if total+len(data)>MAX_UPLOAD_TOTAL:
                fail('STORAGE_LIMIT','Uploaded artifacts are limited to 64 MiB per project; ask its owner to manage retention')
            output=os.open(staging,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            staged=True
            with os.fdopen(output,'wb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno())
            # link is atomic and refuses an existing target, unlike replace/rename.
            os.link(staging,digest,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
            os.fsync(fd)
            os.unlink(staging,dir_fd=fd)
            staged=False
            os.fsync(fd)
        except OSError:
            if staged:
                try:os.unlink(staging,dir_fd=fd);os.fsync(fd)
                except OSError:pass
            # A published complete blob stays immutable even if the event rolls back.
            fail('PATH_UNSAFE','Could not safely store uploaded bytes')
        finally:os.close(fd)

    def _digest_artifact(self,artifact):
        if artifact.get('source')!='uploaded_text':
            return self._digest(artifact['path'])
        import stat
        digest=artifact['sha256']
        if not re.fullmatch(r'[a-f0-9]{64}',digest):fail('ARTIFACT_CORRUPT','Recorded upload digest is malformed; ask the owner to restore from a trusted backup')
        fd=self._upload_dir()
        try:
            filefd=os.open(digest,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            with os.fdopen(filefd,'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):fail('PATH_UNSAFE','Uploaded artifact is missing or unsafe')
                data=handle.read(MAX_INGEST+1)
                if len(data)>MAX_INGEST:fail('ARTIFACT_CORRUPT','Stored upload exceeds the 128 KiB upload bound; ask the owner to restore from a trusted backup')
        except OSError:fail('PATH_UNSAFE','Uploaded artifact is missing or unsafe')
        finally:os.close(fd)
        return hashlib.sha256(data).hexdigest(),len(data),data

    @staticmethod
    def _current_evidence(task, state):
        artifact = task.get('artifact')
        if not artifact:
            return {}
        latest = {}
        belongs = binder(task, state)
        for item in task['evidence']:
            if belongs(item) and item['artifact_revision'] == artifact['revision'] and item['artifact_sha256'] == artifact['sha256']:
                latest[item['check_id']] = item
        return latest

    @staticmethod
    def review_basis(task, state):
        """Remember the exact task evidence and decision displayed in an owner form."""
        artifact = task['artifact']
        evidence = Engine._current_evidence(task, state)
        decisions = task['decisions']
        anchor = decisions[-1]['id'] if decisions else None
        if decisions and decisions[-1]['outcome'] == 'accepted':
            equivalent = Engine._equivalent_acceptances(task, state)
            anchor = next((item['id'] for item in decisions if item['id'] in equivalent), anchor)
        basis = dict(project=state['project_id'], contract=state['contract_revision'],
                     task=task['id'], revision=artifact['revision'], sha256=artifact['sha256'],
                     evidence=sorted(item['id'] for item in evidence.values()),
                     decision=anchor)
        return hashlib.sha256(canonical(basis).encode()).hexdigest()

    @staticmethod
    def _dependency_stamp(task, tasks):
        return {dep: {'artifact': tasks[dep]['artifact']['sha256'], 'decision': tasks[dep]['decisions'][-1]['id']} for dep in task['dependencies'] if tasks[dep].get('artifact') and tasks[dep]['decisions']}

    @staticmethod
    def _equivalent_acceptances(dependency, state):
        """IDs in the uninterrupted run of approvals for exactly the same basis."""
        artifact = dependency['artifact']
        decisions = dependency['decisions']
        belongs = binder(dependency, state)
        equivalent = set()
        for item in reversed(decisions):
            if (item['outcome'] != 'accepted' or not belongs(item)
                    or item['artifact_revision'] != artifact['revision']
                    or item['artifact_sha256'] != artifact['sha256']
                    or item['evidence_ids'] != decisions[-1]['evidence_ids']
                    or item['reason'] != decisions[-1]['reason']):
                break
            equivalent.add(item['id'])
        return equivalent

    @staticmethod
    def _dependency_stamp_matches(recorded, task, tasks, state, equivalents):
        if recorded == Engine._dependency_stamp(task, tasks):
            return True
        if not isinstance(recorded, dict) or set(recorded) != set(task['dependencies']):
            return False
        for dep in task['dependencies']:
            old = recorded[dep]
            dependency = tasks[dep]
            artifact = dependency.get('artifact')
            if (not isinstance(old, dict) or set(old) != {'artifact', 'decision'}
                    or not artifact or old['artifact'] != artifact['sha256']
                    or not isinstance(old['decision'], str)):
                return False
            if dep not in equivalents:
                equivalents[dep] = Engine._equivalent_acceptances(dependency, state)
            if old['decision'] not in equivalents[dep]:
                return False
        return True

    def _now(self):
        now = self.clock()
        try:
            valid = type(now) in (int, float) and math.isfinite(now)
        except OverflowError:
            valid = False
        if not valid:
            fail('BAD_CLOCK', 'Clock must return finite numeric seconds')
        return now

    def _project(self, state, now=None):
        if now is None:
            now = self._now()
        tasks = {t['id']: t for t in state['tasks']}
        done = set()
        equivalents = {}  # Only this projection can reuse an approval history.
        def status(task):
            if task['id'] in done:
                return
            for dep in task['dependencies']:
                status(tasks[dep])
            task['stale_reason'] = ''
            if state.get('revision_scope') == 'task':
                # Exposed so readers can tell which records still apply to the task as now agreed.
                task['task_fingerprint'] = task_fingerprint(state, task)
            artifact = task['artifact']
            if task['lease'] and task['lease']['expires_at'] <= now:
                task['lease'] = None
            result = 'claimed' if task['lease'] else 'unclaimed'
            blocked = [d for d in task['dependencies'] if tasks[d]['status'] != 'accepted']
            if blocked:
                result = 'blocked'; task['stale_reason'] = 'Dependencies need acceptance: ' + ', '.join(blocked)
            elif artifact:
                reason = ''
                belongs = binder(task, state)
                if not belongs(artifact):
                    reason = 'Not registered under this task\'s current agreed definition, goal and constraints' if state.get('revision_scope') == 'task' else 'Contract revision changed'
                elif not self._dependency_stamp_matches(artifact.get('dependencies', {}), task, tasks, state, equivalents):
                    reason = 'Dependency acceptance changed'
                else:
                    try:
                        digest, _, _ = self._digest_artifact(artifact)
                        if digest != artifact['sha256']:
                            reason = 'Artifact bytes changed'
                    except RumboError:
                        reason = 'Artifact is missing or no longer safely readable'
                if reason:
                    result = 'stale'; task['stale_reason'] = reason
                else:
                    result = 'produced'
                    ev = self._current_evidence(task, state)
                    complete = all(ev.get(c['id'], {}).get('outcome') == 'pass' for c in task['acceptance'])
                    if complete:
                        result = 'checks_passed'
                    decisions = [d for d in task['decisions'] if belongs(d) and d['artifact_revision'] == artifact['revision'] and d['artifact_sha256'] == artifact['sha256']]
                    if decisions:
                        last = decisions[-1]
                        if last['outcome'] == 'rejected':
                            result = 'rejected'
                        elif complete and last['evidence_ids'] == sorted(e['id'] for e in ev.values()):
                            result = 'accepted'
            task['status'] = result
            done.add(task['id'])
        for task in state['tasks']:
            status(task)
        return state

    def snapshot(self):
        with self._db() as db:
            return self._project(self._replay(db))

    @staticmethod
    def _question_scope(task_id, related_ids):
        identifier(task_id, 'task_id')
        if related_ids is None:
            return {'mode': 'whole_project'}
        if not isinstance(related_ids, list) or len(related_ids) > 99:
            fail('BAD_INPUT', 'related_task_ids must be a list of up to 99 other task IDs')
        for tid in related_ids:
            identifier(tid, 'related task ID')
        if task_id in related_ids or len(set(related_ids)) != len(related_ids):
            fail('BAD_INPUT', 'List only distinct other task IDs')
        return {'mode': 'declared_tasks', 'related_task_ids': sorted(related_ids)}

    @staticmethod
    def _question_context(state, task_id, scope, *, progress):
        if scope['mode'] == 'whole_project':
            # Unknown context: no selective reuse. Also bind projected state, since lease
            # expiry or local artifact drift can change it without an intervening event.
            return hashlib.sha256(canonical({'v': 2, 'scope': scope, 'task_id': task_id,
                                             'state': state}).encode()).hexdigest()
        # Only the caller can declare the question's non-graph references. Bind the
        # transitive closure of every declared root; never guess scope by parsing prose.
        by_id = {t['id']: t for t in state['tasks']}
        pending = [task_id, *scope['related_task_ids']]
        if any(tid not in by_id for tid in pending):
            return None
        members = {}
        while pending:
            tid = pending.pop()
            if tid in members:
                continue
            t = by_id[tid]
            record = {key: t[key] for key in ('id', 'title', 'dependencies', 'acceptance')}
            if progress:
                # Latest event identities distinguish new checks, re-registrations and re-decisions,
                # even when bytes or outcomes are identical. Questions do not change readiness.
                record.update(status=t['status'], stale_reason=t['stale_reason'],
                              artifact=t['artifact'], lease=t['lease'],
                              last_evidence=t['evidence'][-1]['id'] if t['evidence'] else None,
                              last_decision=t['decisions'][-1]['id'] if t['decisions'] else None)
            members[tid] = record
            pending.extend(t['dependencies'])
        material = dict(v=2, scope=scope, project_id=state['project_id'], task_id=task_id,
                        original_request=state['original_request'], goal=state['goal'],
                        constraints=state['constraints'], decision_owner=state['decision_owner'],
                        demo=state.get('demo', False), revision_scope=state.get('revision_scope', 'contract'),
                        members=members)
        return hashlib.sha256(canonical(material).encode()).hexdigest()

    def observe_question(self, task_id, *, related_task_ids=None):
        """Return the full snapshot used to compose the question plus its scoped precondition."""
        scope = self._question_scope(task_id, related_task_ids)
        state = self.snapshot()
        self._task(task_id, state)
        for tid in scope.get('related_task_ids', []):
            self._task(tid, state)
        state['question_observation'] = dict(version=2, scope=scope, project_id=state['project_id'], task_id=task_id,
            events_count=state['events_count'], ledger_head=state['ledger_head'],
            context_sha256=self._question_context(state, task_id, scope, progress=True))
        return state

    def _check_question(self, db, state, task_id, observed):
        # Caller holds BEGIN IMMEDIATE; no other ledger writer can intervene before append.
        fields(observed, {'version', 'scope', 'project_id', 'task_id', 'events_count', 'ledger_head', 'context_sha256'})
        integer(observed['version'], 'observation version', 2, 2)
        scope = observed['scope']
        fields(scope, {'mode'}, {'related_task_ids'})
        if scope['mode'] == 'whole_project':
            fields(scope, {'mode'})
        elif scope['mode'] == 'declared_tasks':
            fields(scope, {'mode', 'related_task_ids'})
            if scope['related_task_ids'] is None or scope != self._question_scope(task_id, scope['related_task_ids']):
                fail('BAD_INPUT', 'Use the declared scope exactly as returned by the observation')
        else:
            fail('BAD_INPUT', 'Unknown question observation scope')
        identifier(task_id, 'task_id')
        identifier(observed['task_id'], 'observed task_id')
        identifier(observed['project_id'], 'observed project_id')
        seq = integer(observed['events_count'], 'observed events_count', 1, MAX_EVENTS)
        for key in ('ledger_head', 'context_sha256'):
            if not isinstance(observed[key], str) or not re.fullmatch(r'[0-9a-f]{64}', observed[key]):
                fail('BAD_INPUT', key + ' must be a lowercase SHA-256 digest')

        def stale():
            fail('STALE_QUESTION', 'Read the current task and its prerequisites, then reconsider the question')

        if (observed['project_id'] != state['project_id'] or observed['task_id'] != task_id
                or db.execute('SELECT digest FROM events WHERE seq=?', (seq,)).fetchone() != (observed['ledger_head'],)
                or observed['context_sha256'] != self._question_context(state, task_id, scope, progress=True)):
            stale()
        # Content equality alone would accept task removal/recreation or an intervening edit
        # subsequently reverted. Check the intervening contract versions, not every sibling edit.
        if scope['mode'] == 'whole_project':
            return
        current = None
        for payload, in db.execute('SELECT payload FROM events WHERE seq>? ORDER BY seq', (seq,)):
            event = json.loads(payload)
            if event['action'] == 'revise_contract':
                if current is None:
                    current = self._question_context(state, task_id, scope, progress=False)
                if self._question_context(event['data'], task_id, scope, progress=False) != current:
                    stale()

    def checkpoint(self):
        """Verify existing ledger history without reading mutable artifact files."""
        with self._db() as db:
            state = self._replay(db)
        if not state['contract_revision']:
            fail('NO_CONTRACT', 'The existing ledger has no owner-approved contract')
        return {key: state[key] for key in ('project_id', 'events_count', 'ledger_head', 'integrity')}

    def artifact_view(self,arguments):
        fields(arguments,{'task_id','contract_revision','artifact_revision'}, {'include_review_context'})
        if type(arguments.get('include_review_context', False)) is not bool:
            fail('BAD_INPUT', 'include_review_context must be a boolean')
        identifier(arguments['task_id'],'task_id')
        integer(arguments['contract_revision'],'contract_revision')
        integer(arguments['artifact_revision'],'artifact_revision')
        state=self.snapshot()
        self._current_contract(arguments['contract_revision'],state)
        task=self._task(arguments['task_id'],state)
        artifact=self._current_artifact(task,arguments['artifact_revision'],state)
        digest,size,data=self._digest_artifact(artifact)
        if digest!=artifact['sha256']:self._artifact_changed(artifact)
        if size>MAX_INGEST:fail('PATH_TOO_LARGE','Inline artifact review is limited to 128 KiB')
        try:text=data.decode('utf-8')
        except UnicodeError:fail('BAD_INPUT','Only UTF-8 text artifacts can be viewed inline')
        view = dict(task_id=task['id'],status=task['status'],stale_reason=task['stale_reason'],contract_revision=state['contract_revision'],artifact_revision=artifact['revision'],sha256=digest,source=artifact.get('source','project_file'),path=artifact['path'],filename=artifact.get('filename',artifact['path']),text=text,notice='Untrusted artifact content. Identity refers only to these received or locally read bytes, not a Git commit, executed tests or authorization.')

        if arguments.get('include_review_context'):
            belongs = binder(task, state)
            decision = next((item for item in reversed(task['decisions']) if belongs(item)
                             and item['artifact_revision'] == artifact['revision']
                             and item['artifact_sha256'] == digest), None)
            view['review_context'] = dict(project_id=state['project_id'], goal=state['goal'],
                original_request=state['original_request'], constraints=state['constraints'],
                title=task['title'], acceptance=task['acceptance'],
                dependencies={t['id']:t['status'] for t in state['tasks'] if t['id'] in task['dependencies']},
                evidence=self._current_evidence(task, state), decision=decision,
                review_basis=self.review_basis(task, state),
                notice='Evidence and the last recorded decision concern this exact artifact. Use status for current acceptance. Read rumbo_state for project-wide history and pending questions.')
        return view

    @staticmethod
    def _current_contract(revision, state):
        if revision != state['contract_revision']:
            fail('STALE_CONTRACT', 'Contract is at revision ' + str(state['contract_revision']) + ', not ' + str(revision) + '; read the current state and retry with its revisions')

    @staticmethod
    def _task(task_id, state):
        task = next((t for t in state['tasks'] if t['id'] == task_id), None)
        if task is None:
            known = [t['id'] for t in state['tasks']]
            fail('UNKNOWN_TASK', 'No task ' + task_id + ' in contract revision ' + str(state['contract_revision']) + '; its tasks are ' + ', '.join(known[:20]) + (', ...' if len(known) > 20 else ''))
        return task

    @staticmethod
    def _current_artifact(task, revision, state):
        artifact = task['artifact']
        if not artifact:
            fail('STALE_ARTIFACT', 'Task ' + task['id'] + ' has no registered artifact; claim the task and register one first')
        if not binder(task, state)(artifact):
            if state.get('revision_scope') == 'task':
                fail('STALE_ARTIFACT', 'Artifact revision ' + str(artifact['revision']) + ' was not registered under task ' + task['id'] + '\'s current agreed definition, goal and constraints; register it again under revision ' + str(state['contract_revision']))
            fail('STALE_ARTIFACT', 'Artifact revision ' + str(artifact['revision']) + ' was registered under contract revision ' + str(artifact['contract_revision']) + '; register it again under revision ' + str(state['contract_revision']))
        if revision != artifact['revision']:
            fail('STALE_ARTIFACT', 'Artifact is at revision ' + str(artifact['revision']) + ', not ' + str(revision) + '; read the current state and retry with its revisions')
        return artifact

    @staticmethod
    def _artifact_changed(artifact):
        fail('ARTIFACT_CHANGED', 'Bytes no longer match registered artifact revision ' + str(artifact['revision']) + '; register the artifact again, then rerun its checks')

    def _previous_question(self, args, state):
        key = identifier(args['request_key'], 'request_key')
        if 'observation' not in args:
            fail('BAD_INPUT', 'request_key requires the observation used to compose the question')
        for record in state['requests']:
            if (record.get('request_key') == key and record['actor'] == self.actor
                    and record.get('request_role') == self.role):
                if (record['task_id'] != args['task_id'] or record['question'] != args['question']
                        or canonical(record['observation']) != canonical(args['observation'])):
                    fail('QUESTION_KEY_CONFLICT', 'This request_key already identifies a different question or observation. Read state and reconcile the original request before starting a distinct one.')
                return record
        return None

    @staticmethod
    def _acknowledge_question(state, record, appended):
        state['decision_request_ack'] = dict(event_id=record['id'], request_key=record['request_key'],
            actor=record['actor'], role=record['request_role'], task_id=record['task_id'],
            recorded_contract_revision=record['contract_revision'], appended=appended)
        return state

    def execute(self, action, arguments):
        if action not in ACTION_FIELDS:
            fail('UNKNOWN_ACTION', 'Supported actions are ' + ', '.join(sorted(ACTION_FIELDS)))
        if action in ('create_contract','revise_contract','decide') and self.role != 'human':
            fail('FORBIDDEN', 'Only the authenticated human decision owner can perform this action')
        if self.role == 'viewer':
            fail('FORBIDDEN', 'Read-only principal')
        if action == 'submit_review' and self.role != 'reviewer':
            fail('FORBIDDEN', 'A configured reviewer principal is required')
        fields(arguments, *ACTION_FIELDS[action])
        if len(canonical(arguments).encode()) > (1024*1024 if action=='ingest_artifact' else 256000):
            fail('BAD_INPUT', 'Action too large')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._replay(db)
            # Linearize eligibility after lock acquisition and replay. Metadata
            # uses this same decision time even if artifact work takes longer.
            now = self._now()
            state = self._project(state, now)
            keyed_question = action == 'request_decision' and 'request_key' in arguments
            if keyed_question:
                previous = self._previous_question(arguments, state)
                if previous is not None:
                    # This acknowledges an existing event, even if the task has since changed.
                    # A new append still needs capacity and a fresh observation below.
                    return self._acknowledge_question(state, previous, appended=False)
            if state['events_count'] >= MAX_EVENTS:
                fail('LEDGER_LIMIT', 'Ledger holds its maximum of ' + str(MAX_EVENTS) + ' events; ask its owner to archive the project and start a new one')
            if action == 'request_decision' and 'observation' in arguments:
                self._check_question(db, state, arguments['task_id'], arguments['observation'])
            data = self._prepare(action, arguments, state, now)
            event = dict(action=action, data=data, actor=self.actor, role=self.role, at=now)
            raw = canonical(event); prev = state['ledger_head']
            total=db.execute('SELECT COALESCE(SUM(length(payload)),0) FROM events').fetchone()[0]
            if total+len(raw)>MAX_LEDGER_BYTES:fail('LEDGER_LIMIT','Event payloads are limited to 16 MiB per project; ask its owner to archive or manage retention')
            if action == 'ingest_artifact':
                self._store_upload(data['artifact']['sha256'], arguments['content'].encode('utf-8'))
            digest = hashlib.sha256((prev+'\n'+raw).encode()).hexdigest()
            db.execute('INSERT INTO events VALUES(?,?,?,?)', (state['events_count']+1,raw,prev,digest))
            result = self._project(self._replay(db))
            if keyed_question:
                return self._acknowledge_question(result, data, appended=True)
            return result

    def _prepare(self, action, args, state, now):
        rev = state['contract_revision']
        eventid = 'e' + str(state['events_count']+1)
        if action == 'create_contract':
            if rev:
                fail('CONTRACT_EXISTS', 'Project ' + str(state['project_id']) + ' already has a contract at revision ' + str(rev) + '; its owner changes it with revise_contract')
            validate_contract(args, self.actor)
            return dict(copy.deepcopy(args), contract_revision=1, contract_change_reason='Initial owner-approved contract')
        if not rev:
            fail('NO_CONTRACT', 'The human owner must initialize a contract first')
        if action in ('revise_contract','decide') and self.actor != state['decision_owner']:
            fail('FORBIDDEN', 'Only the configured decision owner may decide')
        if action == 'revise_contract':
            integer(args['expected_revision'], 'expected_revision')
            self._current_contract(args['expected_revision'], state)
            string(args['reason'], 'reason')
            validate_contract(args['contract'], self.actor)
            if args['contract']['project_id'] != state['project_id']:
                fail('BAD_INPUT', 'Project id is immutable')
            return dict(copy.deepcopy(args['contract']), demo=args['contract'].get('demo', False), contract_revision=rev+1, contract_change_reason=args['reason'])
        identifier(args['task_id'], 'task_id')
        task = self._task(args['task_id'], state)
        scoped = state.get('revision_scope') == 'task'
        fingerprint = dict(task_fingerprint=task_fingerprint(state, task)) if scoped else {}
        if action == 'request_decision':
            string(args['question'], 'question')
            if 'request_key' in args:
                fingerprint.update(request_key=args['request_key'], request_role=self.role)
            if 'observation' in args:
                fingerprint['observation'] = copy.deepcopy(args['observation'])
            return dict(id=eventid, task_id=task['id'], question=args['question'], actor=self.actor, contract_revision=rev, at=now, **fingerprint)
        integer(args['contract_revision'], 'contract_revision')
        self._current_contract(args['contract_revision'], state)
        if action == 'claim_task':
            ttl = integer(args['lease_seconds'], 'lease_seconds', 30, 3600)
            if task['status'] == 'blocked':
                fail('DEPENDENCY_BLOCKED', task['stale_reason'])
            if task['lease'] and task['lease']['actor'] != self.actor:
                fail('LEASE_CONFLICT', 'Another actor holds an unexpired lease')
            return dict(task_id=task['id'], lease=dict(actor=self.actor, expires_at=now+ttl, contract_revision=rev))
        tasks = {t['id']: t for t in state['tasks']}
        if action in ('submit_artifact','ingest_artifact'):
            if not task['lease']:
                fail('LEASE_REQUIRED', 'No unexpired lease on ' + task['id'] + '; claim the task first. Leases expire and do not carry over to a new connection')
            if task['lease']['actor'] != self.actor:
                fail('LEASE_REQUIRED', 'Another actor holds the unexpired lease on ' + task['id'] + '; only the lease holder can register its artifact')
            if task['status'] == 'blocked':
                fail('DEPENDENCY_BLOCKED', task['stale_reason'])
            for criterion in task['acceptance']:
                if criterion['kind'] == 'project_file_at':
                    required = criterion['value']
                    if action == 'ingest_artifact' or project_file_path(args['path']) != project_file_path(required):
                        fail('DESTINATION_MISMATCH', 'This task requires the project file ' + required
                             + '. Check the current owner-selected destination and register that file.')
            if 'expected_artifact_revision' in args:
                previous = integer(args['expected_artifact_revision'], 'expected_artifact_revision', minimum=0)
                current = task['artifact']['revision'] if task['artifact'] else 0
                if previous != current:
                    fail('STALE_REGISTRATION', 'Artifact revision is now ' + str(current)
                         + '. Read current state before deciding whether any registration is still needed.')
            if 'expected_sha256' in args:
                expected = args['expected_sha256']
                if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                    fail('BAD_INPUT', 'expected_sha256 must be the lowercase SHA-256 of the reviewed file')
            if action=='ingest_artifact':
                filename=string(args['filename'],'filename',128)
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',filename) or filename.lower().endswith(('.pem','.key','.p12','.pfx')):
                    fail('PATH_INVALID','Use a simple display filename; paths and credential filenames are not accepted')
                if not isinstance(args['content'],str):
                    fail('BAD_INPUT','content must be UTF-8 text')
                try:
                    data=args['content'].encode('utf-8')
                except UnicodeError:
                    fail('BAD_INPUT','content must be valid UTF-8 text')
                if len(data)>MAX_INGEST:
                    fail('PATH_TOO_LARGE','Uploaded text is limited to 128 KiB of UTF-8 bytes')
                digest=hashlib.sha256(data).hexdigest();size=len(data)
                metadata=dict(path='uploaded:'+filename,filename=filename,source='uploaded_text')
            else:
                digest, size, _ = self._digest(args['path'])
                metadata=dict(path=args['path'],source='project_file')
            if 'expected_sha256' in args and digest != args['expected_sha256']:
                fail('REVIEWED_BYTES_CHANGED', 'Contents differ from the reviewed digest. Reread the authorized source before registering it.')
            revision = task['artifact']['revision']+1 if task['artifact'] else 1
            return dict(task_id=task['id'], artifact=dict(**metadata, sha256=digest, size=size, revision=revision, contract_revision=rev, maker=self.actor, at=now, dependencies=self._dependency_stamp(task,tasks), **fingerprint))
        integer(args['artifact_revision'], 'artifact_revision')
        artifact = self._current_artifact(task, args['artifact_revision'], state)
        digest, _, raw = self._digest_artifact(artifact)
        if digest != artifact['sha256']:
            self._artifact_changed(artifact)
        if task['status'] == 'blocked':
            fail('DEPENDENCY_BLOCKED', task['stale_reason'])
        if not self._dependency_stamp_matches(artifact.get('dependencies', {}), task, tasks, state, {}):
            fail('DEPENDENCY_BLOCKED', 'A dependency was decided or changed after artifact revision ' + str(artifact['revision']) + ' was registered; register the artifact again')
        common = dict(actor=self.actor, role=self.role, contract_revision=rev, artifact_revision=artifact['revision'], artifact_sha256=digest, at=now, **fingerprint)
        if action == 'run_checks':
            evidence = []
            json_parsed = False
            json_value = None
            for check in task['acceptance']:
                kind = check['kind']
                if kind == 'manual_review':
                    continue
                passed = False
                try:
                    if kind == 'project_file_at':
                        passed = (artifact.get('source', 'project_file') == 'project_file'
                                  and Path(artifact['path']) == Path(check['value']))
                    elif kind == 'sha256':
                        passed = digest == check['value']
                    elif kind == 'file_contains':
                        passed = check['value'] in raw.decode('utf-8')
                    elif kind == 'json_equals':
                        if not json_parsed:
                            # Cache failed parses too, only for these exact bytes in this action.
                            json_parsed = True
                            json_value = artifact_json(raw)
                        value = json_value
                        passed = isinstance(value, dict) and check['key'] in value and canonical(value[check['key']]) == canonical(check['value'])
                except (ValueError, UnicodeError, RumboError, RecursionError):
                    passed = False
                evidence.append(dict(common, id=eventid+'-'+check['id'], kind='deterministic', check_id=check['id'], outcome='pass' if passed else 'fail', detail=('Project file at ' + check['value'] if kind == 'project_file_at' and passed else kind+' evaluated against the recorded artifact bytes')))
            return dict(task_id=task['id'], evidence=evidence)
        if action == 'submit_review':
            if self.actor == artifact['maker']:
                fail('SELF_REVIEW', 'Reviewer must differ from artifact maker')
            identifier(args['check_id'], 'check_id')
            if not any(c['id'] == args['check_id'] and c['kind'] == 'manual_review' for c in task['acceptance']):
                fail('BAD_INPUT', 'Only manual_review criteria accept assertions')
            if args['outcome'] not in ('pass','fail','uncertain'):
                fail('BAD_INPUT', 'Review outcome must be pass, fail or uncertain')
            string(args['detail'], 'detail')
            return dict(task_id=task['id'], evidence=[dict(common, id=eventid, kind='reviewer_assertion', check_id=args['check_id'], outcome=args['outcome'], detail=args['detail'])])
        if action == 'decide':
            if 'expected_review_basis' in args and args['expected_review_basis'] != self.review_basis(task, state):
                fail('STALE_REVIEW', 'The review basis changed. Reopen the task and inspect its current evidence and owner decision.')
            if args['outcome'] not in ('accepted','rejected'):
                fail('BAD_INPUT', 'Decision must be accepted or rejected')
            string(args['reason'], 'reason')
            ev = self._current_evidence(task, state)
            if args['outcome'] == 'accepted' and not all(ev.get(c['id'],{}).get('outcome') == 'pass' for c in task['acceptance']):
                fail('CHECKS_INCOMPLETE', 'Every current acceptance criterion needs passing evidence')
            return dict(task_id=task['id'], decision=dict(common, id=eventid, outcome=args['outcome'], reason=args['reason'], evidence_ids=sorted(e['id'] for e in ev.values())))
        fail('UNKNOWN_ACTION', 'Supported actions are ' + ', '.join(sorted(ACTION_FIELDS)))
