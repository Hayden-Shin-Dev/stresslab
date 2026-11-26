# Market Regime API 계약서 (v1) — 프론트엔드·백엔드 담당자용

- 기본 경로: `/api/v1/market-regime` · 메서드: GET만 · 인증: 기존 API와 같은 방식(APIM/게이트웨이에서 처리)
- 데이터 기준: 확정 일별 자료(`gold_stress_daily`). 장중 실시간 시세와는 별개입니다. 하루 1회 갱신됩니다.
- 모든 응답에 `notice`(투자 권유 아님 문구)가 들어 있고, 화면에 **반드시 표시**해야 합니다.

## 1. 엔드포인트

| 경로 | 쿼리 | 응답 `data` | 용도 |
|---|---|---|---|
| `/snapshot` | – | 스냅샷 전체 (envelope 없음) | **대시보드는 이것 하나만 호출** |
| `/current` | – | 현재 국면 카드 | 다른 화면의 작은 위젯 |
| `/history` | `start`, `end` (YYYY-MM-DD) 또는 `years` (0 < N ≤ 30) | 일별 이력 | 차트 범위 조회 |
| `/runs` | `regime` (bull·sideways·bear), `limit` (1~1000) | 국면 구간 | 이력 표 |
| `/summary` | – | 국면별 특성 | |
| `/transitions` | – | 과거 전이 빈도 | |
| `/similar` | – | 유사 과거 시기 (이후 수익률 없음) | |
| `/model` | – | 모델·검증·데이터 품질 | |
| `/health` | – | `{status: ok/unavailable, ...}` | 모니터링 |

`/snapshot`을 뺀 응답은 아래 envelope로 감쌉니다.

```json
{ "meta": { "schema": "market_regime_snapshot", "schema_version": 1, "snapshot_version": "20261118T001503Z",
            "as_of": "2026-11-17", "generated_at": "…", "data_mode": "fabric_gold",
            "model_version": "regime-hmm-v1", "payload_sha256": "…", "notice": "과거 데이터 기반 시장 분석이며 …" },
  "data": { … } }
```

**캐시.** 모든 응답에 `ETag`와 `Cache-Control: public, max-age=300`이 붙습니다. `If-None-Match`를 보내면 변경이 없을 때 304가 옵니다.

**오류.**

| HTTP | `detail.code` | 의미 |
|---|---|---|
| 400 | `BAD_REQUEST` | 날짜 형식, 범위, regime 값 오류 |
| 503 | `NO_SNAPSHOT_ROWS`, `POSTGRES_UNAVAILABLE:*`, `SNAPSHOT_SHA256_MISMATCH`, `SYNTHETIC_SNAPSHOT_REFUSED`, `SNAPSHOT_SCHEMA_UNSUPPORTED` | 표시할 스냅샷 없음 → 화면은 "준비 중" 처리 |

PostgreSQL이 잠시 끊기면 API는 마지막으로 읽은 정상 스냅샷을 계속 돌려줍니다.

## 2. 스냅샷 구조 (`/snapshot`)

| 키 | 형식 | 설명 |
|---|---|---|
| `schema`, `schema_version` | `"market_regime_snapshot"`, `1` | 버전이 다르면 화면에서 거부 |
| `snapshot_version`, `generated_at`, `as_of` | string | 생성 시각(UTC), 기준 거래일 |
| `data_mode` | `fabric_gold` \| `synthetic_fixture` | **synthetic이면 '샘플 데이터' 배너 필수** |
| `notice` | string | 투자 권유 아님 문구 |
| `regimes` | `[{code, name, description}]` | 순서 고정: bull(상승장), sideways(횡보장), bear(폭락장) |
| `current` | object | 아래 3절 |
| `history` | `[{date, kospi, regime, p_bull, p_sideways, p_bear, raw, basis}]` | 일별. `basis`: `wf` 실시간 판정, `is` 초기 학습 구간 |
| `runs` | `[{run_id, regime_code, regime_name, start, end, days, kospi_change_pct, label_basis, is_current}]` | 국면이 이어진 구간. `kospi_change_pct`는 그 구간 동안의 **과거 실제** 변화 |
| `summary` | `[{regime_code, day_share, n_runs, avg_run_days, median_run_days, max_run_days, ann_return_pct, ann_vol_pct, avg_corr_60d, avg_breadth_down_pct, avg_vix, days_walk_forward}]` | 국면별 과거 관측치 |
| `transitions` | `{order, daily_counts[3][3], daily_frequency[3][3], run_transition_counts[3][3]}` | 행 = 오늘, 열 = 다음 거래일 |
| `similar` | `{asof, k, method, features[{id,label}], features_dropped, query_z{}, neighbors[{rank, date, distance, regime_code, regime_name, regime_run_days, label_basis, z{}}]}` | z는 표준화 값(σ) |
| `validation` | object | 하락 구간 포착, 실루엣, 안정성, 일치율 |
| `model` | object | 방법, 피처, 학습 기준일, 재학습 주기, 라벨 규칙, BIC |
| `quality` | object | 기간, 종목 수, 제외일 수, 경고 문구 |
| `data_version` | object | Gold 스냅샷 버전과 해시 |

크기는 약 380KB(gzip 약 35KB)입니다. 이력이 늘어나면 하루에 약 0.13KB씩 커집니다.

## 3. `current` 필드와 화면 규칙

| 필드 | 예 | 화면 규칙 |
|---|---|---|
| `regime_code`, `regime_name` | `"bull"`, `"상승장"` | 큰 글씨 + 색 점. 색만으로 구분하지 않고 항상 이름을 함께 표시 |
| `confidence` | `0.93` | 표시 국면의 모델 확률. "모델 확률 93%" |
| `probabilities` | `{bull, sideways, bear}` | 합 = 1. 막대 3개 |
| `pending_switch` | `null` 또는 `{to_code, to_name, consecutive_days, required_days}` | 값이 있으면 "횡보장 전환 확인 중 (1/5일)" 표시. 이때 `confidence`가 낮은 것이 정상입니다 |
| `days_in_regime`, `regime_since` | `85`, `"2026-07-22"` | "85거래일 · 시작일 2026.07.22" |
| `changes_last_252d` | `6` | 최근 1년 국면 전환 횟수 |
| `label_basis` | `walk_forward` | `initial_in_sample`이면 "초기 학습 구간" 표시 |
| `indicators[]` | `{id, label, unit, value, percentile}` | `percentile`은 과거 전체에서 현재 값 이하였던 날의 비율(0~100) |

**단위 표기**(토론 AI 프롬프트 V1.6 규칙과 동일): `%`는 소수 둘째 자리, `bp`는 정수, `pt`는 소수 둘째 자리, `corr`는 소수 둘째 자리. 금리 **수준(%)**과 금리 **변화(bp)**를 섞지 않습니다.

**색 토큰.** 색각이상 검증을 통과한 조합입니다(라이트/다크).

| 국면 | 라이트 | 다크 |
|---|---|---|
| 상승장 | `#1baf7a` | `#199e70` |
| 횡보장 | `#6250d6` | `#9085e9` |
| 폭락장 | `#eb6834` | `#d95926` |

빨강·파랑은 한국 시세 표기(빨강 = 상승, 파랑 = 하락)와 충돌해서 쓰지 않았습니다.

**쓰지 말아야 할 표현**: "예측", "다음 주 폭락 확률", "매수/매도 신호", "안전". 확률은 현재 상태에 대한 모델 추정치이고, 유사 시기는 이후 결과를 보여 주지 않습니다.

## 4. 대시보드 모듈 옵션 (`RegimeDashboard.mount(el, options)`)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `apiBase` | – | `{apiBase}/api/v1/market-regime/snapshot`을 호출 |
| `snapshotUrl` | – | 스냅샷 JSON 주소를 직접 지정(apiBase보다 우선) |
| `snapshot` | – | 이미 받은 스냅샷 객체 |
| `fallbackUrl` | – | API 실패 시 예비 파일(개발용). 사용 중이면 배너 표시 |
| `theme` | `auto` | `auto`는 OS 설정과 `html[data-theme]`을 따름, `light`·`dark` 강제 |
| `initialTab` | `overview` | `overview`·`history`·`similar`·`model` |
| `fetchInit` | `{}` | 인증 헤더 등 fetch 옵션 |

반환값은 `{ refresh(), setTheme(t), destroy() }`입니다. CSS는 모두 `.rgm-` 접두사로 범위를 제한해 기존 화면 스타일과 충돌하지 않습니다. 글꼴은 `--rgm-font` 변수로 바꿀 수 있습니다.

## 5. 프레임워크 예시

**React**
```jsx
import { useEffect, useRef } from "react";
// index.html에 regime-dashboard.css / regime-dashboard.js를 먼저 로드
export default function RegimePage({ apiBase }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = window.RegimeDashboard.mount(ref.current, { apiBase });
    return () => d.destroy();
  }, [apiBase]);
  return <div ref={ref} />;
}
```

**바닐라 JS 메뉴 전환** — `web/regime-dashboard/menu-integration-example.html` 참고.

## 6. 토론 AI와의 관계 (참고)

토론 AI 프롬프트 V1.6에는 국면 분석용 `metric_id`가 정의돼 있지 않고, 프롬프트도 새 `metric_id`를 임의로 만들지 말라고 규정합니다. 그래서 이 API를 토론 근거(`D_sources`)로 쓰려면 프롬프트 담당자와 서버 담당자가 항목을 따로 정의해야 합니다. 이번 산출물에는 포함하지 않았습니다.
