"""승인 모델 패키지: 승인 게이트, 포장, 검증, MLflow 기록. (analytics/README.md 12.5절)

패키지 내용(README 정의): 전처리·모델·잔차·피처 순서·버전·지원 범위. API 담당도 같은 패키지를 씁니다.

    gate = check_gates(metrics, load_criteria('evaluation/approval_criteria.json'))
    pkg  = build_package(model_dir, out_dir, ...)       # MANIFEST.json에 파일별 sha256
    verify_package(out_dir)                              # 배포 직전·API 로딩 직전에 다시 확인
    log_package_to_mlflow(out_dir, experiment=..., model_name=...)

원칙
  - 승인 기준 숫자가 하나라도 비어 있거나 필수 항목이 없으면 승인하지 않습니다(fail closed).
  - 승인 전 패키지도 만들 수 있지만 status는 'candidate'이고, MLflow 모델 등록은 'approved'일 때만 합니다.
  - "데이터 연결 완료"와 "모델 승인"은 다른 사건입니다. 이 모듈은 승인을 선언하지 않고 기준 충족 여부만 기록합니다.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PACKAGE_VERSION = 'model-package-v1.0'
CORE_FILES = ('model.joblib', 'model_card.json', 'market_scale.csv', 'calibration_residuals.csv')
META_FILE = 'package_meta.json'
MANIFEST_FILE = 'MANIFEST.json'

# 이 항목이 기준표에 없으면 승인 불가. 숫자는 사람이 정합니다(저장소에 기준이 없음).
REQUIRED_CHECKS = ('coverage90_gap', 'extreme_shock_degradation', 'gold_reconciliation',
                   'ridge_migration', 'leak_tests')
OPS = ('<=', '>=', '==', 'between')


# ------------------------------------------------------------------ 승인 게이트
@dataclass
class GateResult:
    approved: bool
    checks: list = field(default_factory=list)
    undefined: list = field(default_factory=list)
    missing_required: list = field(default_factory=list)
    criteria_version: str | None = None

    def to_dict(self):
        return {'approved': self.approved, 'criteria_version': self.criteria_version, 'checks': self.checks,
                'undefined_thresholds': self.undefined, 'missing_required_checks': self.missing_required}


def load_criteria(path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else None


def _threshold_defined(c: dict) -> bool:
    if c.get('op') not in OPS:
        return False
    if c['op'] == 'between':
        return c.get('low') is not None and c.get('high') is not None
    return c.get('threshold') is not None


def _passes(op, value, c):
    if op == '<=':
        return value <= c['threshold']
    if op == '>=':
        return value >= c['threshold']
    if op == '==':
        return value == c['threshold']
    return c['low'] <= value <= c['high']


def check_gates(metrics: dict, criteria: dict | None) -> GateResult:
    """metrics: {지표 이름: 값}. criteria가 없거나 불완전하면 approved=False."""
    if not criteria or not criteria.get('checks'):
        return GateResult(False, [], ['criteria_missing'], list(REQUIRED_CHECKS), None)
    out, undefined = [], []
    ids = {c.get('id') for c in criteria['checks']}
    missing_required = [r for r in REQUIRED_CHECKS if r not in ids]
    for c in criteria['checks']:
        cid = c.get('id')
        if not _threshold_defined(c):
            undefined.append(cid)
            out.append({'id': cid, 'status': 'undefined_threshold', 'metric': c.get('metric')})
            continue
        v = metrics.get(c.get('metric'))
        if v is None or (isinstance(v, float) and v != v):
            out.append({'id': cid, 'status': 'metric_missing', 'metric': c.get('metric')})
            continue
        ok = bool(_passes(c['op'], v, c))
        out.append({'id': cid, 'status': 'pass' if ok else 'fail', 'metric': c['metric'], 'value': v,
                    'op': c['op'], 'threshold': c.get('threshold', [c.get('low'), c.get('high')])})
    approved = not undefined and not missing_required and all(o['status'] == 'pass' for o in out)
    return GateResult(approved, out, undefined, missing_required, criteria.get('criteria_version'))


# ------------------------------------------------------------------ 지원 범위
def support_range(train: pd.DataFrame, feature_order: list[str]) -> dict:
    """학습 구간에서 입력별 최소·최대·분위수. 이 범위 밖 입력은 외삽입니다."""
    miss = [c for c in feature_order if c not in train.columns]
    if miss:
        raise KeyError(f'학습 표에 없는 입력 컬럼: {miss}')
    out = {}
    for c in feature_order:
        s = pd.to_numeric(train[c], errors='coerce').dropna()
        out[c] = {'min': float(s.min()), 'max': float(s.max()), 'p01': float(s.quantile(.01)),
                  'p99': float(s.quantile(.99)), 'n': int(len(s))}
    return out


# ------------------------------------------------------------------ 포장·검증
def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build_package(model_dir, out_dir, *, feature_order: list[str], versions: dict, support: dict,
                  gate: GateResult, extra_files: dict | None = None, source: dict | None = None) -> dict:
    """model_dir(train.write_model 결과)을 복사해 패키지를 만듭니다. 이미 있는 out_dir은 덮어쓰지 않습니다."""
    model_dir, out = Path(model_dir), Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'{out} 가 비어 있지 않습니다. 새 폴더 이름을 쓰세요(패키지는 불변).')
    missing = [f for f in CORE_FILES if not (model_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f'모델 폴더에 없음: {missing}')
    out.mkdir(parents=True, exist_ok=True)
    names = list(CORE_FILES)
    for f in names:
        shutil.copy2(model_dir / f, out / f)
    for name, src in (extra_files or {}).items():
        shutil.copy2(src, out / name)
        names.append(name)
    meta = {'package_version': PACKAGE_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'status': 'approved' if gate.approved else 'candidate',
            'approval': gate.to_dict(), 'feature_order': list(feature_order), 'versions': versions,
            'support_range': support, 'source': source or {},
            'note': ('status가 approved여도 사람의 최종 확인 기록은 별도입니다. candidate는 배포 대상이 아닙니다.')}
    (out / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    names.append(META_FILE)
    files = {n: sha256_file(out / n) for n in sorted(names)}
    package_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
    manifest = {'package_version': PACKAGE_VERSION, 'package_id': package_id, 'files': files}
    (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    return {'package_id': package_id, 'status': meta['status'], 'dir': str(out), 'files': files}


def verify_package(pkg_dir, *, require_approved: bool = False) -> dict:
    """해시·필수 파일·메타를 다시 확인합니다. 어긋나면 ValueError."""
    d = Path(pkg_dir)
    mf = d / MANIFEST_FILE
    if not mf.exists():
        raise ValueError(f'{MANIFEST_FILE} 없음')
    manifest = json.loads(mf.read_text(encoding='utf8'))
    problems = []
    for n, h in manifest['files'].items():
        p = d / n
        if not p.exists():
            problems.append(f'missing:{n}')
        elif sha256_file(p) != h:
            problems.append(f'hash_mismatch:{n}')
    extra = sorted(f.name for f in d.iterdir() if f.is_file() and f.name != MANIFEST_FILE and f.name not in manifest['files'])
    if extra:
        problems.append(f'unlisted_files:{extra}')
    for n in (*CORE_FILES, META_FILE):
        if n not in manifest['files']:
            problems.append(f'required_not_in_manifest:{n}')
    if problems:
        raise ValueError('패키지 검증 실패: ' + '; '.join(problems))
    meta = json.loads((d / META_FILE).read_text(encoding='utf8'))
    if not meta.get('feature_order') or not meta.get('versions') or not meta.get('support_range'):
        raise ValueError('package_meta에 feature_order/versions/support_range 중 비어 있는 것이 있습니다.')
    if require_approved and meta.get('status') != 'approved':
        raise ValueError(f"승인된 패키지가 아닙니다(status={meta.get('status')}).")
    return {'package_id': manifest['package_id'], 'status': meta['status'], 'files': len(manifest['files'])}


# ------------------------------------------------------------------ MLflow
def log_package_to_mlflow(pkg_dir, *, experiment: str, model_name: str, tracking_uri: str | None = None,
                          register: bool = True, mlflow_module=None) -> dict:
    """패키지를 MLflow 실행에 기록합니다. 모델 등록은 status=approved일 때만 합니다.

    Fabric 노트북에는 mlflow가 들어 있습니다. 없으면 기록을 건너뛰고 사유를 반환합니다(오류로 막지 않음).
    """
    d = Path(pkg_dir)
    info = verify_package(d)
    meta = json.loads((d / META_FILE).read_text(encoding='utf8'))
    mlflow = mlflow_module
    if mlflow is None:
        try:
            import mlflow
        except ImportError:
            return {'logged': False, 'reason': 'mlflow 미설치', **info}
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    with mlflow.start_run() as run:
        mlflow.set_tags({'package_id': info['package_id'], 'package_status': meta['status'],
                         'package_version': meta['package_version']})
        for k, v in meta['versions'].items():
            mlflow.log_param(k, str(v)[:250])
        for c in meta['approval']['checks']:
            if isinstance(c.get('value'), (int, float)) and not isinstance(c.get('value'), bool):
                mlflow.log_metric(c['id'], float(c['value']))
        mlflow.log_artifacts(str(d), artifact_path='package')
        run_id = run.info.run_id
    registered = None
    if register and meta['status'] == 'approved':
        registered = mlflow.register_model(f'runs:/{run_id}/package', model_name)
    return {'logged': True, 'run_id': run_id, 'registered': registered is not None,
            'registered_version': getattr(registered, 'version', None),
            'register_skipped_reason': None if (registered or not register) else f"status={meta['status']}", **info}
