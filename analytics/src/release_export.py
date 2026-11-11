"""버전 고정 배포 내보내기: Gold 피처/근거 표를 PostgreSQL에 새 릴리스로 적재합니다. (제안 설계)

저장소에는 PostgreSQL 스키마가 아직 없습니다(infra/services '구현 전'). 아래 표 구조는 제안이며,
market-state 서비스 담당과 합의가 끝나면 DDL만 바꾸면 됩니다. 로직은 DB-API 연결(psycopg 등) 하나로 동작합니다.

흐름 (한 릴리스 = dataset_version + feature_version + 내용 해시)
  1. stage    릴리스 행을 status='staged'로 적재. 읽는 쪽은 포인터만 보므로 이 단계는 보이지 않음
  2. validate DB에서 다시 읽어 행 수·키 중복·내용 해시를 원본과 대조
  3. switch   한 트랜잭션에서 포인터를 새 릴리스로 옮기고 이전 릴리스를 'retired'로 (삭제하지 않음)
  rollback_pointer(): 이전 릴리스로 포인터만 되돌림
같은 입력을 다시 실행하면 같은 release_id가 나와 중복 적재하지 않습니다(멱등).
접속 정보는 코드에 쓰지 않습니다. fabric_io.get_secret으로 받은 연결을 넘기세요.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

KEY_COLS = ('trading_date', 'asset_id')
POINTER_DEFAULT = 'current'
_IDENT = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')
TABLES = {'versions': 'release_versions', 'pointer': 'release_pointer', 'features': 'release_features'}


class ExportError(RuntimeError):
    pass


# ------------------------------------------------------------------ 표 준비
def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """키 + 값 컬럼을 정렬·정규화합니다. 키 중복, 키 결측, 비수치 값 컬럼은 오류."""
    miss = [k for k in KEY_COLS if k not in df.columns]
    if miss:
        raise ExportError(f'키 컬럼 없음: {miss}')
    f = df.copy()
    f['trading_date'] = pd.to_datetime(f['trading_date']).dt.strftime('%Y-%m-%d')
    f['asset_id'] = f['asset_id'].astype(str)
    if f[list(KEY_COLS)].isna().any().any():
        raise ExportError('키에 결측이 있습니다.')
    if f.duplicated(list(KEY_COLS)).any():
        raise ExportError('(trading_date, asset_id) 중복이 있습니다.')
    bad_names = [c for c in f.columns if not _IDENT.match(c)]
    if bad_names:
        raise ExportError(f'SQL 컬럼명으로 쓸 수 없는 이름: {bad_names}')
    vals = [c for c in f.columns if c not in KEY_COLS]
    nonnum = [c for c in vals if not pd.api.types.is_numeric_dtype(f[c]) or pd.api.types.is_bool_dtype(f[c])]
    if nonnum:
        raise ExportError(f'수치가 아닌 값 컬럼: {nonnum} (제외하거나 별도 변환 필요)')
    for c in vals:
        f[c] = f[c].astype('float64')
    if np.isinf(f[vals].to_numpy()).any():
        raise ExportError('무한대 값이 있습니다.')
    return f[list(KEY_COLS) + vals].sort_values(list(KEY_COLS)).reset_index(drop=True)


def content_hash(f: pd.DataFrame) -> str:
    """정규화된 표의 내용 해시. 컬럼 순서·행 순서가 같으면 같은 값."""
    h = hashlib.sha256()
    h.update('|'.join(f.columns).encode())
    for row in f.itertuples(index=False):
        h.update(('\x1f'.join('' if (isinstance(v, float) and v != v) else
                              (repr(float(v)) if isinstance(v, (float, np.floating)) else str(v)) for v in row)
                  + '\n').encode())
    return h.hexdigest()


def release_id_for(dataset_version: str, feature_version: str, sha: str) -> str:
    return hashlib.sha256(f'{dataset_version}|{feature_version}|{sha}'.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ SQL 도우미
class _Db:
    def __init__(self, conn, paramstyle: str, dialect: str):
        if paramstyle not in ('qmark', 'format'):
            raise ValueError("paramstyle은 'qmark'(sqlite) 또는 'format'(psycopg)")
        if dialect not in ('sqlite', 'postgres'):
            raise ValueError("dialect는 'sqlite' 또는 'postgres'")
        self.conn, self.ph, self.dialect = conn, ('?' if paramstyle == 'qmark' else '%s'), dialect

    def q(self, sql: str) -> str:
        return sql.replace('?', self.ph)

    def run(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(self.q(sql), tuple(params))
        return cur

    def many(self, sql, rows):
        cur = self.conn.cursor()
        cur.executemany(self.q(sql), rows)

    def fetch(self, sql, params=()):
        return self.run(sql, params).fetchall()

    @property
    def num(self):
        return 'DOUBLE PRECISION' if self.dialect == 'postgres' else 'REAL'

    @property
    def date(self):
        return 'DATE' if self.dialect == 'postgres' else 'TEXT'


def ensure_schema(db: _Db, frame: pd.DataFrame) -> None:
    """표가 없으면 만들고, 있으면 값 컬럼이 같은지 확인합니다(스키마 변경은 별도 마이그레이션으로)."""
    vals = [c for c in frame.columns if c not in KEY_COLS]
    t = TABLES
    db.run(f'''CREATE TABLE IF NOT EXISTS {t['versions']} (
        release_id TEXT PRIMARY KEY, dataset_version TEXT NOT NULL, feature_version TEXT NOT NULL,
        as_of TEXT, source_ref TEXT, row_count INTEGER NOT NULL, content_sha256 TEXT NOT NULL,
        status TEXT NOT NULL, created_utc TEXT NOT NULL)''')
    db.run(f'''CREATE TABLE IF NOT EXISTS {t['pointer']} (
        name TEXT PRIMARY KEY, release_id TEXT NOT NULL, switched_utc TEXT NOT NULL)''')
    cols = ',\n        '.join(f'{c} {db.num}' for c in vals)
    db.run(f'''CREATE TABLE IF NOT EXISTS {t['features']} (
        release_id TEXT NOT NULL, trading_date {db.date} NOT NULL, asset_id TEXT NOT NULL,
        {cols},
        PRIMARY KEY (release_id, trading_date, asset_id))''')
    have = _table_columns(db, t['features'])
    want = ['release_id', *KEY_COLS, *vals]
    if have != want:
        raise ExportError(f'기존 {t["features"]} 컬럼과 다릅니다(스키마 드리프트). 있음={have}, 필요={want}')
    db.conn.commit()


def _table_columns(db: _Db, table: str) -> list[str]:
    if db.dialect == 'sqlite':
        return [r[1] for r in db.fetch(f'PRAGMA table_info({table})')]
    return [r[0] for r in db.fetch('SELECT column_name FROM information_schema.columns WHERE table_name = ? '
                                   'ORDER BY ordinal_position', (table,))]


# ------------------------------------------------------------------ 단계
def stage_release(db: _Db, frame: pd.DataFrame, *, release_id, dataset_version, feature_version, as_of, source_ref, sha):
    vals = [c for c in frame.columns if c not in KEY_COLS]
    names = ['release_id', *KEY_COLS, *vals]
    ins = f"INSERT INTO {TABLES['features']} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})"
    try:
        db.run(f"INSERT INTO {TABLES['versions']} (release_id, dataset_version, feature_version, as_of, source_ref, "
               "row_count, content_sha256, status, created_utc) VALUES (?,?,?,?,?,?,?,?,?)",
               (release_id, dataset_version, feature_version, as_of, source_ref, len(frame), sha, 'staged',
                datetime.now(timezone.utc).isoformat(timespec='seconds')))
        rows = ((release_id, *[None if (isinstance(v, float) and v != v) else v for v in r])
                for r in frame[list(names[1:])].itertuples(index=False, name=None))
        batch = []
        for r in rows:
            batch.append(r)
            if len(batch) >= 5000:
                db.many(ins, batch)
                batch = []
        if batch:
            db.many(ins, batch)
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise


def read_release(db: _Db, release_id: str, columns: list[str]) -> pd.DataFrame:
    rows = db.fetch(f"SELECT {', '.join(columns)} FROM {TABLES['features']} WHERE release_id = ? "
                    'ORDER BY trading_date, asset_id', (release_id,))
    f = pd.DataFrame(rows, columns=columns)
    f['trading_date'] = f['trading_date'].map(lambda x: str(x)[:10])
    for c in columns:
        if c not in KEY_COLS:
            f[c] = f[c].astype('float64')
    return f


def validate_release(db: _Db, release_id: str, expected: pd.DataFrame, sha: str) -> dict:
    back = read_release(db, release_id, list(expected.columns))
    problems = []
    if len(back) != len(expected):
        problems.append(f'row_count db={len(back)} expected={len(expected)}')
    if back.duplicated(list(KEY_COLS)).any():
        problems.append('duplicate_keys')
    if not problems and content_hash(back) != sha:
        problems.append('content_hash_mismatch')
    if problems:
        raise ExportError('검증 실패: ' + '; '.join(problems))
    return {'rows': len(back), 'content_sha256': sha}


def _switch(db: _Db, release_id: str, pointer: str) -> None:
    try:
        old = db.fetch(f"SELECT release_id FROM {TABLES['pointer']} WHERE name = ?", (pointer,))
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if old:
            db.run(f"UPDATE {TABLES['pointer']} SET release_id = ?, switched_utc = ? WHERE name = ?",
                   (release_id, now, pointer))
            if old[0][0] != release_id:
                db.run(f"UPDATE {TABLES['versions']} SET status = 'retired' WHERE release_id = ?", (old[0][0],))
        else:
            db.run(f"INSERT INTO {TABLES['pointer']} (name, release_id, switched_utc) VALUES (?,?,?)",
                   (pointer, release_id, now))
        db.run(f"UPDATE {TABLES['versions']} SET status = 'active' WHERE release_id = ?", (release_id,))
        db.conn.commit()          # 포인터 전환과 상태 갱신은 한 트랜잭션
    except Exception:
        db.conn.rollback()
        raise


def current_release(db: _Db, pointer: str = POINTER_DEFAULT) -> str | None:
    r = db.fetch(f"SELECT release_id FROM {TABLES['pointer']} WHERE name = ?", (pointer,))
    return r[0][0] if r else None


def discard_release(db: _Db, release_id: str) -> None:
    """검증에 실패한 staged 릴리스를 지웁니다. 포인터가 가리키는 릴리스는 지우지 않습니다."""
    if current_release(db) == release_id:
        raise ExportError('현재 포인터가 가리키는 릴리스는 삭제할 수 없습니다.')
    try:
        db.run(f"DELETE FROM {TABLES['features']} WHERE release_id = ?", (release_id,))
        db.run(f"UPDATE {TABLES['versions']} SET status = 'failed' WHERE release_id = ? AND status = 'staged'", (release_id,))
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise


# ------------------------------------------------------------------ 공개 함수
def export_release(conn, df: pd.DataFrame, *, dataset_version: str, feature_version: str, as_of: str,
                   source_ref: str, pointer: str = POINTER_DEFAULT, paramstyle: str = 'format',
                   dialect: str = 'postgres', dry_run: bool = False) -> dict:
    """새 릴리스를 적재하고 검증한 뒤 포인터를 옮깁니다. dry_run이면 표 검사와 해시 계산만 합니다."""
    if not all([dataset_version, feature_version, as_of, source_ref]):
        raise ExportError('dataset_version, feature_version, as_of, source_ref는 모두 필요합니다.')
    frame = prepare_frame(df)
    sha = content_hash(frame)
    rid = release_id_for(dataset_version, feature_version, sha)
    result = {'release_id': rid, 'rows': len(frame), 'content_sha256': sha, 'pointer': pointer}
    if dry_run:
        return {**result, 'action': 'dry_run'}
    db = _Db(conn, paramstyle, dialect)
    ensure_schema(db, frame)
    prior = db.fetch(f"SELECT status FROM {TABLES['versions']} WHERE release_id = ?", (rid,))
    if prior and prior[0][0] in ('active', 'retired', 'staged'):
        validate_release(db, rid, frame, sha)           # 이미 있어도 내용은 다시 확인
        if current_release(db, pointer) == rid:
            return {**result, 'action': 'noop_already_current'}
        _switch(db, rid, pointer)
        return {**result, 'action': 'switched_existing'}
    if prior and prior[0][0] == 'failed':
        db.run(f"DELETE FROM {TABLES['versions']} WHERE release_id = ?", (rid,))
        db.conn.commit()
    stage_release(db, frame, release_id=rid, dataset_version=dataset_version, feature_version=feature_version,
                  as_of=as_of, source_ref=source_ref, sha=sha)
    try:
        validate_release(db, rid, frame, sha)
    except ExportError:
        discard_release(db, rid)
        raise
    _switch(db, rid, pointer)
    return {**result, 'action': 'exported'}


def rollback_pointer(conn, release_id: str, *, pointer: str = POINTER_DEFAULT, paramstyle: str = 'format',
                     dialect: str = 'postgres') -> dict:
    """포인터를 이미 검증된 이전 릴리스로 되돌립니다(데이터 삭제 없음)."""
    db = _Db(conn, paramstyle, dialect)
    r = db.fetch(f"SELECT status, row_count FROM {TABLES['versions']} WHERE release_id = ?", (release_id,))
    if not r or r[0][0] not in ('active', 'retired'):
        raise ExportError(f'되돌릴 수 없는 릴리스: {release_id} ({r[0][0] if r else "없음"})')
    n = db.fetch(f"SELECT COUNT(*) FROM {TABLES['features']} WHERE release_id = ?", (release_id,))[0][0]
    if n != r[0][1]:
        raise ExportError(f'릴리스 행 수가 기록과 다릅니다: {n} != {r[0][1]}')
    _switch(db, release_id, pointer)
    return {'release_id': release_id, 'pointer': pointer, 'action': 'rolled_back'}


def list_releases(conn, *, paramstyle: str = 'format', dialect: str = 'postgres') -> pd.DataFrame:
    db = _Db(conn, paramstyle, dialect)
    rows = db.fetch(f"SELECT release_id, dataset_version, feature_version, as_of, row_count, status, created_utc "
                    f"FROM {TABLES['versions']} ORDER BY created_utc")
    return pd.DataFrame(rows, columns=['release_id', 'dataset_version', 'feature_version', 'as_of', 'row_count',
                                       'status', 'created_utc'])
