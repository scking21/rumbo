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
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
ACTION_FIELDS = {
    'create_contract': ({'project_id','goal','original_request','decision_owner','constraints','tasks'}, {'demo'}),
    'revise_contract': ({'contract','expected_revision','reason'}, set()),
    'claim_task': ({'task_id','contract_revision','lease_seconds'}, set()),
    'submit_artifact': ({'task_id','contract_revision','path'}, set()),
    'ingest_artifact': ({'task_id','contract_revision','filename','content'}, set()),
    'run_checks': ({'task_id','contract_revision','artifact_revision'}, set()),
    'submit_review': ({'task_id','contract_revision','artifact_revision','check_id','outcome','detail'}, set()),
    'request_decision': ({'task_id','question'}, set()),
    'decide': ({'task_id','contract_revision','artifact_revision','outcome','reason'}, set()),
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


def validate_contract(data, actor):
    fields(data, *ACTION_FIELDS['create_contract'])
    identifier(data['project_id'], 'project_id')
    string(data['goal'], 'goal'); string(data['original_request'], 'original_request', 16000)
    identifier(data['decision_owner'], 'decision_owner')
    if data['decision_owner'] != actor:
        fail('FORBIDDEN', 'The authenticated decision owner must own the contract')
    if 'demo' in data and type(data['demo']) is not bool:
        fail('BAD_INPUT', 'demo must be boolean')
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
        for check in checks:
            if not isinstance(check, dict):
                fail('BAD_INPUT', 'Acceptance must contain objects')
            kind = check.get('kind')
            required = {'id','kind'}
            extras = {'file_contains': {'value'}, 'json_equals': {'key','value'}, 'sha256': {'value'}, 'manual_review': {'prompt'}}
            if not isinstance(kind, str) or kind not in extras:
                fail('BAD_INPUT', 'Unsupported check kind')
            fields(check, required | extras[kind])
            identifier(check['id'], 'check id')
            if check['id'] in seen:
                fail('BAD_INPUT', 'Duplicate check id')
            seen.add(check['id'])
            if kind in ('file_contains', 'sha256'):
                string(check['value'], 'check value', 16000)
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
            fail('DEPENDENCY_CYCLE')
        if tid in visited:
            return
        visiting.add(tid)
        for dep in by_id[tid]['dependencies']:
            visit(dep)
        visiting.remove(tid); visited.add(tid)
    for tid in ids:
        visit(tid)
    if len(canonical(data).encode()) > 256000:
        fail('BAD_INPUT', 'Contract too large')


class Engine:
    def __init__(self, root, actor, role, clock=None, read_only=False):
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
        self.clock = clock or time.time
        state = self.root / '.rumbo'
        if state.is_symlink():
            fail('PATH_UNSAFE', 'State directory may not be a symlink')
        if read_only:
            if not state.is_dir():
                fail('NO_CONTRACT', 'No existing project ledger; initialize an owner-approved contract first')
        else:
            state.mkdir(mode=0o700, exist_ok=True)
        self.db_path = state / 'state.sqlite3'
        if self.db_path.is_symlink():
            fail('PATH_UNSAFE', 'State database may not be a symlink')
        if read_only:
            if not self.db_path.is_file():
                fail('NO_CONTRACT', 'No existing project ledger; initialize an owner-approved contract first')
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
            else:
                db=sqlite3.connect(str(self.db_path),timeout=15)
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
            fail('LEDGER_LIMIT')
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
        if not isinstance(relative, str) or not relative or len(relative) > 512 or '\\' in relative or '\x00' in relative:
            fail('PATH_INVALID')
        path = Path(relative)
        if path.is_absolute() or any(p in ('.','..') for p in relative.split('/')):
            fail('PATH_INVALID', 'Use a project-relative file path without traversal')
        forbidden = {'.git','.rumbo','.ssh','.aws','.codex','.agents','.docker','.kube','.config','.gcloud','.azure','.gnupg','.password-store','.npmrc','.pypirc','.netrc','.git-credentials','.gitconfig','.yarnrc','.yarnrc.yml','id_rsa','id_ed25519','node_modules','__pycache__'}
        for part in path.parts:
            if part in forbidden or part == '.env' or part.startswith('.env.') or part.lower().endswith(('.pem','.key','.p12','.pfx')):
                fail('PATH_PRIVATE', 'Private/configuration paths cannot be artifacts')
        candidate = self.root / path
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                fail('PATH_UNSAFE', 'Symlink artifacts are not supported')
        try:
            if not candidate.resolve().is_relative_to(self.root):
                fail('PATH_UNSAFE')
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
        if not re.fullmatch(r'[a-f0-9]{64}',digest):fail('ARTIFACT_CORRUPT')
        fd=self._upload_dir()
        try:
            filefd=os.open(digest,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            with os.fdopen(filefd,'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):fail('PATH_UNSAFE')
                data=handle.read(MAX_INGEST+1)
                if len(data)>MAX_INGEST:fail('ARTIFACT_CORRUPT')
        except OSError:fail('PATH_UNSAFE','Uploaded artifact is missing or unsafe')
        finally:os.close(fd)
        return hashlib.sha256(data).hexdigest(),len(data),data

    @staticmethod
    def _current_evidence(task, revision):
        artifact = task.get('artifact')
        if not artifact:
            return {}
        latest = {}
        for item in task['evidence']:
            if item['contract_revision'] == revision and item['artifact_revision'] == artifact['revision'] and item['artifact_sha256'] == artifact['sha256']:
                latest[item['check_id']] = item
        return latest

    @staticmethod
    def _dependency_stamp(task, tasks):
        return {dep: {'artifact': tasks[dep]['artifact']['sha256'], 'decision': tasks[dep]['decisions'][-1]['id']} for dep in task['dependencies'] if tasks[dep].get('artifact') and tasks[dep]['decisions']}

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
        def status(task):
            if task['id'] in done:
                return
            for dep in task['dependencies']:
                status(tasks[dep])
            task['stale_reason'] = ''
            artifact = task['artifact']
            if task['lease'] and task['lease']['expires_at'] <= now:
                task['lease'] = None
            result = 'claimed' if task['lease'] else 'unclaimed'
            blocked = [d for d in task['dependencies'] if tasks[d]['status'] != 'accepted']
            if blocked:
                result = 'blocked'; task['stale_reason'] = 'Dependencies need acceptance: ' + ', '.join(blocked)
            elif artifact:
                reason = ''
                if artifact['contract_revision'] != state['contract_revision']:
                    reason = 'Contract revision changed'
                elif artifact.get('dependencies', {}) != self._dependency_stamp(task, tasks):
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
                    ev = self._current_evidence(task, state['contract_revision'])
                    complete = all(ev.get(c['id'], {}).get('outcome') == 'pass' for c in task['acceptance'])
                    if complete:
                        result = 'checks_passed'
                    decisions = [d for d in task['decisions'] if d['contract_revision'] == state['contract_revision'] and d['artifact_revision'] == artifact['revision'] and d['artifact_sha256'] == artifact['sha256']]
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

    def checkpoint(self):
        """Verify existing ledger history without reading mutable artifact files."""
        with self._db() as db:
            state = self._replay(db)
        if not state['contract_revision']:
            fail('NO_CONTRACT', 'The existing ledger has no owner-approved contract')
        return {key: state[key] for key in ('project_id', 'events_count', 'ledger_head', 'integrity')}

    def artifact_view(self,arguments):
        fields(arguments,{'task_id','contract_revision','artifact_revision'})
        identifier(arguments['task_id'],'task_id')
        integer(arguments['contract_revision'],'contract_revision')
        integer(arguments['artifact_revision'],'artifact_revision')
        state=self.snapshot()
        if arguments['contract_revision']!=state['contract_revision']:fail('STALE_CONTRACT')
        task=next((t for t in state['tasks'] if t['id']==arguments['task_id']),None)
        if not task:fail('UNKNOWN_TASK')
        artifact=task['artifact']
        if not artifact or artifact['revision']!=arguments['artifact_revision'] or artifact['contract_revision']!=state['contract_revision']:
            fail('STALE_ARTIFACT')
        digest,size,data=self._digest_artifact(artifact)
        if digest!=artifact['sha256']:fail('ARTIFACT_CHANGED')
        if size>MAX_INGEST:fail('PATH_TOO_LARGE','Inline artifact review is limited to 128 KiB')
        try:text=data.decode('utf-8')
        except UnicodeError:fail('BAD_INPUT','Only UTF-8 text artifacts can be viewed inline')
        return dict(task_id=task['id'],status=task['status'],stale_reason=task['stale_reason'],contract_revision=state['contract_revision'],artifact_revision=artifact['revision'],sha256=digest,source=artifact.get('source','project_file'),path=artifact['path'],filename=artifact.get('filename',artifact['path']),text=text,notice='Untrusted artifact content. Identity refers only to these received or locally read bytes, not a Git commit, executed tests or authorization.')

    def execute(self, action, arguments):
        if action not in ACTION_FIELDS:
            fail('UNKNOWN_ACTION')
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
            if state['events_count'] >= MAX_EVENTS:
                fail('LEDGER_LIMIT')
            data = self._prepare(action, arguments, state, now)
            event = dict(action=action, data=data, actor=self.actor, role=self.role, at=now)
            raw = canonical(event); prev = state['ledger_head']
            total=db.execute('SELECT COALESCE(SUM(length(payload)),0) FROM events').fetchone()[0]
            if total+len(raw)>MAX_LEDGER_BYTES:fail('LEDGER_LIMIT','Event payloads are limited to 16 MiB per project; ask its owner to archive or manage retention')
            if action == 'ingest_artifact':
                self._store_upload(data['artifact']['sha256'], arguments['content'].encode('utf-8'))
            digest = hashlib.sha256((prev+'\n'+raw).encode()).hexdigest()
            db.execute('INSERT INTO events VALUES(?,?,?,?)', (state['events_count']+1,raw,prev,digest))
            return self._project(self._replay(db))

    def _prepare(self, action, args, state, now):
        rev = state['contract_revision']
        eventid = 'e' + str(state['events_count']+1)
        if action == 'create_contract':
            if rev:
                fail('CONTRACT_EXISTS')
            validate_contract(args, self.actor)
            return dict(copy.deepcopy(args), contract_revision=1, contract_change_reason='Initial owner-approved contract')
        if not rev:
            fail('NO_CONTRACT', 'The human owner must initialize a contract first')
        if action in ('revise_contract','decide') and self.actor != state['decision_owner']:
            fail('FORBIDDEN', 'Only the configured decision owner may decide')
        if action == 'revise_contract':
            integer(args['expected_revision'], 'expected_revision')
            if args['expected_revision'] != rev:
                fail('STALE_CONTRACT')
            string(args['reason'], 'reason')
            validate_contract(args['contract'], self.actor)
            if args['contract']['project_id'] != state['project_id']:
                fail('BAD_INPUT', 'Project id is immutable')
            return dict(copy.deepcopy(args['contract']), demo=args['contract'].get('demo', False), contract_revision=rev+1, contract_change_reason=args['reason'])
        identifier(args['task_id'], 'task_id')
        task = next((t for t in state['tasks'] if t['id'] == args['task_id']), None)
        if task is None:
            fail('UNKNOWN_TASK')
        if action == 'request_decision':
            string(args['question'], 'question')
            return dict(id=eventid, task_id=task['id'], question=args['question'], actor=self.actor, contract_revision=rev, at=now)
        integer(args['contract_revision'], 'contract_revision')
        if args['contract_revision'] != rev:
            fail('STALE_CONTRACT')
        if action == 'claim_task':
            ttl = integer(args['lease_seconds'], 'lease_seconds', 30, 3600)
            if task['status'] == 'blocked':
                fail('DEPENDENCY_BLOCKED')
            if task['lease'] and task['lease']['actor'] != self.actor:
                fail('LEASE_CONFLICT', 'Another actor holds an unexpired lease')
            return dict(task_id=task['id'], lease=dict(actor=self.actor, expires_at=now+ttl, contract_revision=rev))
        tasks = {t['id']: t for t in state['tasks']}
        if action in ('submit_artifact','ingest_artifact'):
            if not task['lease'] or task['lease']['actor'] != self.actor:
                fail('LEASE_REQUIRED')
            if task['status'] == 'blocked':
                fail('DEPENDENCY_BLOCKED')
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
            revision = task['artifact']['revision']+1 if task['artifact'] else 1
            return dict(task_id=task['id'], artifact=dict(**metadata, sha256=digest, size=size, revision=revision, contract_revision=rev, maker=self.actor, at=now, dependencies=self._dependency_stamp(task,tasks)))
        artifact = task['artifact']
        integer(args['artifact_revision'], 'artifact_revision')
        if not artifact or args['artifact_revision'] != artifact['revision'] or artifact['contract_revision'] != rev:
            fail('STALE_ARTIFACT')
        digest, _, raw = self._digest_artifact(artifact)
        if digest != artifact['sha256']:
            fail('ARTIFACT_CHANGED')
        if task['status'] == 'blocked' or artifact.get('dependencies',{}) != self._dependency_stamp(task,tasks):
            fail('DEPENDENCY_BLOCKED')
        common = dict(actor=self.actor, role=self.role, contract_revision=rev, artifact_revision=artifact['revision'], artifact_sha256=digest, at=now)
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
                    if kind == 'sha256':
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
                evidence.append(dict(common, id=eventid+'-'+check['id'], kind='deterministic', check_id=check['id'], outcome='pass' if passed else 'fail', detail=kind+' evaluated against the recorded artifact bytes'))
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
            if args['outcome'] not in ('accepted','rejected'):
                fail('BAD_INPUT', 'Decision must be accepted or rejected')
            string(args['reason'], 'reason')
            ev = self._current_evidence(task, rev)
            if args['outcome'] == 'accepted' and not all(ev.get(c['id'],{}).get('outcome') == 'pass' for c in task['acceptance']):
                fail('CHECKS_INCOMPLETE', 'Every current acceptance criterion needs passing evidence')
            return dict(task_id=task['id'], decision=dict(common, id=eventid, outcome=args['outcome'], reason=args['reason'], evidence_ids=sorted(e['id'] for e in ev.values())))
        fail('UNKNOWN_ACTION')
