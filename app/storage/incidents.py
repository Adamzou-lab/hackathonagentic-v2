"""Arrêt explicite du stockage et preuve de secours indépendante de SQLite."""
import json
import hashlib
import os
import re
import sqlite3
import sys
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path


class StorageUnavailable(Exception):
    """Erreur publique stable : aucun chemin, SQL ou texte d'exception amont."""

    def __init__(self, code='storage_sqlite_error'):
        self.code = code
        super().__init__(code)


class IncidentLog:
    def __init__(self, path):
        self.path = Path(path)

    def record(self, code, operation, mission_id=None):
        record = {
            'at': datetime.now(timezone.utc).isoformat(),
            'kind': 'dependency_failed',
            'data': {'dependency': 'sqlite', 'operation': operation,
                     'code': code, 'reaction': 'stop'},
        }
        if isinstance(mission_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', mission_id):
            record['mission_id'] = mission_id
        encoded = json.dumps(record, ensure_ascii=False) + '\n'
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                remaining = encoded.encode('utf-8')
                while remaining:
                    written = os.write(descriptor, remaining)
                    if not written:
                        raise OSError()
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            # Aucune exception ni chemin ne sont interpolés dans le secours.
            record['delivery'] = 'stderr'
            try:
                sys.stderr.write(json.dumps(record, ensure_ascii=False) + '\n')
                sys.stderr.flush()
            except (OSError, ValueError, AttributeError):
                # Le stockage reste en échec, même si aucun canal n'est disponible.
                pass

    def read_recent(self, limit=100):
        """Relit au plus 1 Mio et reconstruit une liste de champs autorisés."""
        limit = max(1, min(100, int(limit)))
        try:
            with self.path.open('rb') as stream:
                stream.seek(0, os.SEEK_END)
                start = max(0, stream.tell() - 1024 * 1024)
                stream.seek(start)
                if start:
                    stream.readline()  # Ignorer une éventuelle première ligne partielle.
                lines = stream.read(1024 * 1024).splitlines()
        except FileNotFoundError:
            return []
        except OSError:
            raise StorageUnavailable('incident_log_unavailable') from None
        codes = {'storage_file_missing', 'storage_file_replaced', 'storage_sqlite_error',
                 'storage_path_unavailable', 'storage_identity_unavailable', 'storage_data_invalid'}
        operations = {'connect', 'identity_read', 'identity_write', 'availability_check',
                      'execute', 'executemany', 'executescript', 'cursor', 'cursor_close',
                      'fetchone', 'fetchall', 'fetchmany', 'iterate', 'commit', 'rollback',
                      'close', 'transaction', 'decode'}
        result = []
        for line in reversed(lines):
            try:
                source = json.loads(line)
                data = source['data']
                if source['kind'] != 'dependency_failed' or data['dependency'] != 'sqlite' or data['reaction'] != 'stop':
                    continue
                if data['code'] not in codes or data['operation'] not in operations:
                    continue
                at = datetime.fromisoformat(source['at'])
                if at.tzinfo is None:
                    continue
                item = {'at': at.isoformat(), 'kind': 'dependency_failed',
                        'data': {key: data[key] for key in ('dependency', 'operation', 'code', 'reaction')}}
                mid = source.get('mission_id')
                if isinstance(mid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', mid):
                    item['mission_id'] = mid
                result.append(item)
                if len(result) >= limit:
                    break
            except (ValueError, TypeError, KeyError):
                continue
        return list(reversed(result))


class GuardedCursor:
    def __init__(self, owner, cursor):
        self._owner, self._cursor = owner, cursor

    def execute(self, *args, **kwargs):
        self._owner._run('execute', lambda: self._cursor.execute(*args, **kwargs))
        return self

    def executemany(self, *args, **kwargs):
        self._owner._run('executemany', lambda: self._cursor.executemany(*args, **kwargs))
        return self

    def executescript(self, *args, **kwargs):
        self._owner._run('executescript', lambda: self._cursor.executescript(*args, **kwargs))
        return self

    def fetchone(self):
        return self._owner._run('fetchone', self._cursor.fetchone)

    def fetchall(self):
        return self._owner._run('fetchall', self._cursor.fetchall)

    def fetchmany(self, size=None):
        return self._owner._run('fetchmany', lambda: self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size))

    def __iter__(self):
        return self

    def __next__(self):
        return self._owner._run('iterate', lambda: next(self._cursor))

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def description(self):
        return self._cursor.description

    def close(self):
        try:
            self._cursor.close()
        except sqlite3.Error:
            self._owner._fail('storage_sqlite_error', 'cursor_close')


class GuardedConnection:
    """Vérifie le fichier avant/après chaque opération, y compris les lectures.

    Un défaut est définitif pour cette instance. Une reconnexion automatique ne
    doit jamais transformer une base disparue en nouvelle base vide.
    """

    def __init__(self, path, incident_log):
        self.path = Path(path).absolute()
        self.incident_log = incident_log
        self._failure = None
        self._connection = None
        self._mission_id = None
        suffix = hashlib.sha256(str(self.path).encode()).hexdigest()[:24]
        self.identity_path = self.incident_log.path.parent / ('.lockin-storage-' + suffix + '.json')
        try:
            expected = self._read_identity()
            if expected is not None:
                try:
                    stat = self.path.stat()
                except FileNotFoundError:
                    self._fail('storage_file_missing', 'connect')
                if (stat.st_dev, stat.st_ino) != expected:
                    self._fail('storage_file_replaced', 'connect')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                before = self.path.stat()
            except FileNotFoundError:
                # Capturer l'identité avant sqlite.connect ferme la fenêtre où
                # un remplacement pourrait être pris pour le fichier ouvert.
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    before = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
            self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=0.25)
            stat = self.path.stat()
            self._identity = stat.st_dev, stat.st_ino
            if self._identity != (before.st_dev, before.st_ino):
                self._fail('storage_file_replaced', 'connect')
            if expected is not None and expected != self._identity:
                self._fail('storage_file_replaced', 'connect')
            if expected is None:
                self._write_identity()
        except sqlite3.Error:
            self._fail('storage_sqlite_error', 'connect')
        except OSError:
            self._fail('storage_path_unavailable', 'connect')

    def _read_identity(self):
        try:
            record = json.loads(self.identity_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            self._fail('storage_identity_unavailable', 'identity_read')
        if not isinstance(record, dict) or record.get('version') != 1 or any(
                type(record.get(field)) is not int for field in ('device', 'inode')):
            self._fail('storage_identity_unavailable', 'identity_read')
        return record['device'], record['inode']

    def _write_identity(self):
        try:
            self.identity_path.parent.mkdir(parents=True, exist_ok=True)
            record = {'version': 1, 'device': self._identity[0], 'inode': self._identity[1]}
            descriptor = os.open(self.identity_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if self._read_identity() != self._identity:
                self._fail('storage_file_replaced', 'identity_write')
        except OSError:
            self._fail('storage_identity_unavailable', 'identity_write')

    def _fail(self, code, operation):
        if self._failure is None:
            self._failure = code
            self.incident_log.record(code, operation, self._mission_id)
        if operation in {'connect', 'identity_read', 'identity_write'} and self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
        raise StorageUnavailable(self._failure) from None

    def _check(self, operation):
        if self._failure:
            raise StorageUnavailable(self._failure) from None
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._fail('storage_file_missing', operation)
        except OSError:
            self._fail('storage_path_unavailable', operation)
        if (stat.st_dev, stat.st_ino) != self._identity:
            self._fail('storage_file_replaced', operation)

    @property
    def unavailable(self):
        return self._failure is not None

    def check_available(self):
        self._check('availability_check')

    def _run(self, operation, callback):
        self._check(operation)
        try:
            result = callback()
        except sqlite3.Error:
            self._fail('storage_sqlite_error', operation)
        self._check(operation)
        return result

    def execute(self, *args, **kwargs):
        return GuardedCursor(self, self._run('execute', lambda: self._connection.execute(*args, **kwargs)))

    def executemany(self, *args, **kwargs):
        return GuardedCursor(self, self._run('executemany', lambda: self._connection.executemany(*args, **kwargs)))

    def executescript(self, *args, **kwargs):
        return GuardedCursor(self, self._run('executescript', lambda: self._connection.executescript(*args, **kwargs)))

    def cursor(self):
        return GuardedCursor(self, self._run('cursor', self._connection.cursor))

    def commit(self):
        return self._run('commit', self._connection.commit)

    def rollback(self):
        return self._run('rollback', self._connection.rollback)

    def __enter__(self):
        self._check('transaction')
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            try:
                # Nettoyage de la connexion existante uniquement ; aucune reprise.
                self._connection.rollback()
            except sqlite3.Error:
                if self._failure is None:
                    self._fail('storage_sqlite_error', 'rollback')
            return False
        self.commit()
        return False

    def close(self):
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                if self._failure is None:
                    self._fail('storage_sqlite_error', 'close')


def mission_context(function):
    """Ajoute l'identifiant de mission aux incidents, sans journaliser ses données."""
    @wraps(function)
    def wrapped(self, value, *args, **kwargs):
        previous = self.db._mission_id
        self.db._mission_id = value.get('id') if isinstance(value, dict) else value
        try:
            return function(self, value, *args, **kwargs)
        finally:
            self.db._mission_id = previous
    return wrapped


def json_guard(function):
    """Les anciennes tables JSON bénéficient aussi de l'arrêt assaini."""
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.db._fail('storage_data_invalid', 'decode')
    return wrapped
