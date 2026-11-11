"""승인 게이트 · 모델 패키지 · PostgreSQL 내보내기 점검. (합성 데이터, sqlite로 DB 흐름 대체)

    python analytics/tests/test_release_package.py
    pytest analytics/tests/test_release_package.py

sqlite는 PostgreSQL이 아닙니다. 적재·검증·포인터 전환·롤백의 로직만 확인합니다.
실제 PostgreSQL에서의 타입·권한·성능은 이 테스트가 보증하지 않습니다.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import fabric_io as FIO  # noqa: E402
import model_package as MP  # noqa: E402
import release_export as RE  # noqa: E402
import run_release as RR  # noqa: E402
from test_daily_pipeline import synth_gold  # noqa: E402

try:
    import pyarrow  # noqa: F401
except ImportError:      # pyarrow 없는 환경(클라우드 점검용): 시장 척도 parquet은 패키지에 들어가지 않으므로 대체 저장
    pd.DataFrame.to_parquet = lambda self, path, **k: self.to_csv(path, index=False)

SQL = dict(paramstyle='qmark', dialect='sqlite')
CRIT_OK = {'criteria_version': 't1', 'checks': [
    {'id': 'coverage90_gap', 'metric': 'coverage90_gap', 'op': '<=', 'threshold': 0.05},
    {'id': 'extreme_shock_degradation', 'metric': 'extreme_ratio', 'op': '<=', 'threshold': 1.5},
    {'id': 'gold_reconciliation', 'metric': 'gold_load_errors', 'op': '==', 'threshold': 0},
    {'id': 'ridge_migration', 'metric': 'ridge_migration_gap', 'op': 'between', 'low': -0.1, 'high': 0.1},
    {'id': 'leak_tests', 'metric': 'leak_tests_pass', 'op': '==', 'threshold': True}]}
GOOD = {'coverage90_gap': 0.02, 'extreme_ratio': 1.2, 'gold_load_errors': 0, 'ridge_migration_gap': 0.0,
        'leak_tests_pass': True}
_cache: dict = {}


def gold():
    if 'g' not in _cache:
        g = synth_gold(n=2900)       # 학습 구간 250행 이상이 되도록 합성 날짜를 5년(7의 배수 일수) 앞당김
        for c in g.columns:
            if pd.api.types.is_datetime64_any_dtype(g[c]):
                g[c] = g[c] - pd.Timedelta(days=1820)
        _cache['g'] = g
    return _cache['g']


def cfg(tmp, **kw):
    c = {'gold_kind': 'pandas', 'gold_location': gold(), 'work_dir': str(tmp), 'package_name': 'pkg1'}
    c.update(kw)
    return c


# ---------------------------------------------------------------- 게이트
def test_gate_fails_closed():
    assert not MP.check_gates(GOOD, None).approved
    assert not MP.check_gates(GOOD, {'checks': []}).approved
    missing_req = {'checks': CRIT_OK['checks'][:3]}
    g = MP.check_gates(GOOD, missing_req)
    assert not g.approved and 'ridge_migration' in g.missing_required
    undefined = json.loads(json.dumps(CRIT_OK))
    undefined['checks'][0]['threshold'] = None
    g = MP.check_gates(GOOD, undefined)
    assert not g.approved and g.undefined == ['coverage90_gap']
    g = MP.check_gates({k: v for k, v in GOOD.items() if k != 'coverage90_gap'}, CRIT_OK)
    assert not g.approved and any(c['status'] == 'metric_missing' for c in g.checks)
    g = MP.check_gates({**GOOD, 'coverage90_gap': 0.2}, CRIT_OK)
    assert not g.approved and any(c['status'] == 'fail' for c in g.checks)


def test_gate_passes_only_when_all_pass():
    g = MP.check_gates(GOOD, CRIT_OK)
    assert g.approved and all(c['status'] == 'pass' for c in g.checks)


# ---------------------------------------------------------------- 파이프라인 + 패키지
def test_train_validate_candidate_then_approved():
    with tempfile.TemporaryDirectory() as t:
        out = RR.run_train_validate(cfg(t))                  # 기준표 없음 -> candidate
        assert out['package']['status'] == 'candidate' and out['leak_checks']['passed']
        assert out['mlflow'] is None
        cp = Path(t) / 'crit.json'
        cp.write_text(json.dumps(CRIT_OK), encoding='utf8')
        out2 = RR.run_train_validate(cfg(t, package_name='pkg2', criteria_path=str(cp)),
                                     extra_metrics={k: v for k, v in GOOD.items()
                                                    if k not in ('gold_load_errors', 'leak_tests_pass')})
        assert out2['package']['status'] == 'approved', out2['gate']
        meta = json.loads((Path(t) / 'packages/pkg2/package_meta.json').read_text(encoding='utf8'))
        assert meta['feature_order'] and meta['versions']['feature_version'] and meta['support_range']
        r = MP.verify_package(Path(t) / 'packages/pkg2', require_approved=True)
        assert r['status'] == 'approved'
        try:
            MP.verify_package(Path(t) / 'packages/pkg1', require_approved=True)
            raise AssertionError('candidate가 통과함')
        except ValueError:
            pass


def test_package_tamper_and_overwrite_detected():
    with tempfile.TemporaryDirectory() as t:
        out = RR.run_train_validate(cfg(t))
        d = Path(out['package']['dir'])
        MP.verify_package(d)
        try:
            RR.run_train_validate(cfg(t))                    # 같은 이름 재사용 금지
            raise AssertionError('덮어쓰기 허용됨')
        except FileExistsError:
            pass
        with open(d / 'calibration_residuals.csv', 'a', encoding='utf8') as f:
            f.write('x\n')
        try:
            MP.verify_package(d)
            raise AssertionError('변조 미검출')
        except ValueError as e:
            assert 'hash_mismatch' in str(e)
        (d / 'stray.txt').write_text('x')
        try:
            MP.verify_package(d)
        except ValueError as e:
            assert 'unlisted_files' in str(e)


def test_empty_config_stops_early():
    try:
        RR.run_train_validate({'gold_kind': 'pandas', 'gold_location': gold(), 'work_dir': ''})
        raise AssertionError('빈 설정 통과')
    except ValueError as e:
        assert 'work_dir' in str(e)
    try:
        FIO.GoldSource(kind='delta_path', location='')
        raise AssertionError
    except ValueError:
        pass
    try:
        FIO.get_secret('NOPE_X', environ={})
        raise AssertionError
    except KeyError:
        pass


class FakeMlflow:
    def __init__(self):
        self.calls = []

    class _Run:
        class info:
            run_id = 'r1'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def set_tracking_uri(self, u): self.calls.append(('uri', u))
    def set_experiment(self, e): self.calls.append(('exp', e))
    def start_run(self): return self._Run()
    def set_tags(self, t): self.calls.append(('tags', t))
    def log_param(self, k, v): self.calls.append(('param', k))
    def log_metric(self, k, v): self.calls.append(('metric', k))
    def log_artifacts(self, p, artifact_path=None): self.calls.append(('artifacts', artifact_path))

    def register_model(self, uri, name):
        self.calls.append(('register', uri, name))
        return type('V', (), {'version': '3'})()


def test_mlflow_registers_only_approved():
    with tempfile.TemporaryDirectory() as t:
        cand = RR.run_train_validate(cfg(t))['package']['dir']
        fm = FakeMlflow()
        r = MP.log_package_to_mlflow(cand, experiment='e', model_name='m', mlflow_module=fm)
        assert r['logged'] and not r['registered'] and not any(c[0] == 'register' for c in fm.calls)
        cp = Path(t) / 'c.json'
        cp.write_text(json.dumps(CRIT_OK), encoding='utf8')
        ap = RR.run_train_validate(cfg(t, package_name='ap', criteria_path=str(cp)),
                                   extra_metrics={k: v for k, v in GOOD.items()
                                                  if k not in ('gold_load_errors', 'leak_tests_pass')})['package']['dir']
        fm2 = FakeMlflow()
        r2 = MP.log_package_to_mlflow(ap, experiment='e', model_name='m', mlflow_module=fm2)
        assert r2['registered'] and r2['registered_version'] == '3'


# ---------------------------------------------------------------- 내보내기
def small_frame(n=30, seed=0, shift=0.0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range('2024-01-01', periods=n)
    f = pd.DataFrame([(d, a) for d in days for a in ('000001', '005930')], columns=['trading_date', 'asset_id'])
    f['asset_vol20'] = rng.normal(1, .1, len(f)) + shift
    f['kospi_trend20'] = rng.normal(0, 1, len(f))
    f.loc[3, 'kospi_trend20'] = np.nan
    f['row_usable'] = 1.0
    return f


def kw(**o):
    return {**dict(dataset_version='ds1', feature_version='features-v1.0', as_of='2024-02-09', source_ref='t@v1'),
            **SQL, **o}


def test_export_idempotent_and_atomic_switch():
    conn = sqlite3.connect(':memory:')
    f = small_frame()
    r1 = RE.export_release(conn, f, **kw())
    assert r1['action'] == 'exported'
    r2 = RE.export_release(conn, f.sample(frac=1, random_state=1), **kw())     # 행 순서만 달라도 같은 릴리스
    assert r2['action'] == 'noop_already_current' and r2['release_id'] == r1['release_id']
    n = conn.execute('select count(*) from release_features').fetchone()[0]
    assert n == len(f)
    r3 = RE.export_release(conn, small_frame(shift=1.0), **kw(dataset_version='ds2'))
    assert r3['action'] == 'exported' and r3['release_id'] != r1['release_id']
    rel = RE.list_releases(conn, **SQL).set_index('release_id')['status']
    assert rel[r1['release_id']] == 'retired' and rel[r3['release_id']] == 'active'
    assert RE.current_release(RE._Db(conn, 'qmark', 'sqlite')) == r3['release_id']
    # NaN은 NULL로 저장
    assert conn.execute('select count(*) from release_features where kospi_trend20 is null and release_id=?',
                        (r1['release_id'],)).fetchone()[0] == 1


def test_rollback_and_old_data_kept():
    conn = sqlite3.connect(':memory:')
    a = RE.export_release(conn, small_frame(), **kw())
    b = RE.export_release(conn, small_frame(shift=1.0), **kw(dataset_version='ds2'))
    rb = RE.rollback_pointer(conn, a['release_id'], **SQL)
    assert rb['action'] == 'rolled_back'
    assert RE.current_release(RE._Db(conn, 'qmark', 'sqlite')) == a['release_id']
    st = RE.list_releases(conn, **SQL).set_index('release_id')['status']
    assert st[a['release_id']] == 'active' and st[b['release_id']] == 'retired'
    # 같은 입력 재실행은 이미 있는 이전 릴리스로 포인터만 옮김
    c = RE.export_release(conn, small_frame(shift=1.0), **kw(dataset_version='ds2'))
    assert c['action'] == 'switched_existing' and c['release_id'] == b['release_id']
    try:
        RE.rollback_pointer(conn, 'nope', **SQL)
        raise AssertionError
    except RE.ExportError:
        pass


def test_failed_validation_leaves_pointer_untouched():
    conn = sqlite3.connect(':memory:')
    a = RE.export_release(conn, small_frame(), **kw())
    orig = RE.validate_release

    def corrupt(db, rid, expected, sha):
        db.run('UPDATE release_features SET asset_vol20 = asset_vol20 + 1 WHERE release_id = ? AND asset_id = ?',
               (rid, '000001'))
        db.conn.commit()
        return orig(db, rid, expected, sha)
    RE.validate_release = corrupt
    try:
        RE.export_release(conn, small_frame(shift=2.0), **kw(dataset_version='ds2'))
        raise AssertionError('손상 미검출')
    except RE.ExportError as e:
        assert 'content_hash_mismatch' in str(e)
    finally:
        RE.validate_release = orig
    assert RE.current_release(RE._Db(conn, 'qmark', 'sqlite')) == a['release_id']
    st = RE.list_releases(conn, **SQL)['status'].tolist()
    assert st.count('failed') == 1 and st.count('active') == 1
    assert conn.execute("select count(*) from release_features where release_id != ?", (a['release_id'],)).fetchone()[0] == 0


def test_prepare_frame_rejects_bad_input():
    f = small_frame()
    for bad, msg in [(pd.concat([f, f.iloc[:1]]), '중복'), (f.assign(txt='a'), '수치가 아닌'),
                     (f.rename(columns={'asset_vol20': 'Bad-Name'}), '컬럼명'),
                     (f.assign(asset_vol20=np.inf), '무한대')]:
        try:
            RE.prepare_frame(bad)
            raise AssertionError(msg)
        except RE.ExportError as e:
            assert msg in str(e), (msg, str(e))
    conn = sqlite3.connect(':memory:')
    try:
        RE.export_release(conn, f, **kw(source_ref=''))
        raise AssertionError
    except RE.ExportError:
        pass
    assert RE.export_release(conn, f, **kw(dry_run=True))['action'] == 'dry_run'
    assert conn.execute("select count(*) from sqlite_master").fetchone()[0] == 0     # dry_run은 아무것도 만들지 않음


def test_schema_drift_detected():
    conn = sqlite3.connect(':memory:')
    RE.export_release(conn, small_frame(), **kw())
    try:
        RE.export_release(conn, small_frame().assign(extra_col=1.0), **kw(dataset_version='ds3'))
        raise AssertionError
    except RE.ExportError as e:
        assert '스키마 드리프트' in str(e)


def test_run_export_end_to_end():
    conn = sqlite3.connect(':memory:')
    c = {'gold_kind': 'pandas', 'gold_location': gold(), **SQL}
    r = RR.run_export(c, conn)
    assert r['action'] == 'exported' and r['rows'] > 1000
    r2 = RR.run_export(c, conn)
    assert r2['action'] == 'noop_already_current' and r2['release_id'] == r['release_id']


def main():
    tests = [(k, v) for k, v in globals().items() if k.startswith('test_') and callable(v)]
    bad = 0
    for k, v in tests:
        try:
            v()
            print('통과', k)
        except Exception:
            bad += 1
            print('실패', k)
            traceback.print_exc()
    print(f'{len(tests) - bad}/{len(tests)} 통과')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
