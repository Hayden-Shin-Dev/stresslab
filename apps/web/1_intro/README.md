# WHAT IF 웹사이트 인트로

`apps/web/intro`는 WHAT IF 웹사이트의 인트로 기능만 담습니다. 기존 실시간 확인 화면인 `apps/web/quote-monitor`와 분리되어 있으므로 해당 화면의 데이터 연결과 배포 설정을 변경하지 않습니다.

## 파일

- `index.html`: 인트로 화면과 실시간 화면 진입 링크
- `styles.css`: 인트로 레이아웃과 반응형 스타일
- `voxel-motion.js`: 외부 라이브러리 없는 WebGL2 복셀 애니메이션
- `main.js`: 강도 조절, 일시정지, 시나리오 모션 제어

## 로컬 확인

저장소 루트에서 인트로 미리보기 서버를 실행합니다.

```powershell
node apps/web/1_intro/preview_server.js
```

- 인트로: `http://localhost:3000/apps/web/1_intro/`
- 인트로 설명서: `http://localhost:3000/apps/web/1_intro/README.md`
- 현재 실시간 화면: `http://localhost:3000/apps/web/quote-monitor/`

인트로의 `실시간 화면 시작` 링크는 위 경로로 연결됩니다.

## 통합 범위

- 이 디렉터리는 인트로 UI만 담당합니다.
- 실시간 시세, Fabric, Container App API 호출은 `quote-monitor`의 기존 코드를 사용합니다.
- `apps/web/quote-monitor/deploy.py`는 WHAT IF 랜딩 인트로를 기본 화면으로 배포하고, 기존 실시간 확인 화면을 `/quote-monitor`와 `/market.html` 경로에 유지합니다.
- `setScenario`는 화면 모션을 위한 시각적 강도 매핑이며 금융 예측값이 아닙니다.

## 브라우저 조건

WebGL2를 지원하는 최신 브라우저를 권장합니다. 운영체제에서 모션 감소가 켜진 경우 애니메이션은 정지 상태로 시작합니다.
