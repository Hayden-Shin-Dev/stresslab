# WHAT IF 웹 서비스

로그인 화면과 분석 앱 셸의 원본을 관리합니다. 2차 인트로와 실시간 데이터 화면은 인접한 `apps/web/2_intro` 및 `apps/web/quote-monitor` 폴더에서 가져옵니다.

## 파일

- `index.html`: 기존 0차 소개 화면 소스
- `2_style.css`, `1_skin.css`: 기존 소개 화면 스타일
- `2_script.js`: 기존 소개 화면 동작
- `login.html`, `login.js`: Google 로그인 화면과 초기화 스크립트
- `service-shell.js`, `service-shell.css`: 공통 인증·메뉴·앱 셸
- `WHATIF_AGENT_FIXED_STANDALONE_V3_8_MYROOM (1).html`: 로그인 후 사용할 WHAT IF 분석 앱
- `assets/inline/`: 분석 앱이 참조하는 이미지와 목록
- `preview_server.js`: 저장소 루트 기준 3000포트 미리보기 서버

## 로컬 확인

저장소 루트에서 실행합니다.

```powershell
node apps/web/0.web_main/preview_server.js
```
- 서비스 링크: https://red-field-0b8ece310.1.azurestaticapps.net/
- 첫 화면/로그인: `http://localhost:3000/` 또는 `http://localhost:3000/login`
- 로그인 후 2차 인트로: `http://localhost:3000/2_intro`
- 실시간 데이터: `http://localhost:3000/quote-monitor`
- 워크스페이스: `http://localhost:3000/app` (실제 로그인은 Azure 배포에서 필요)
- 이 설명서: `http://localhost:3000/apps/web/0.web_main/README.md`
- 기존 WebGL 모션 데모: `http://localhost:3000/apps/web/motion-demo/`

## 배포

`apps/web/quote-monitor/deploy.py`는 로그인 화면, 2차 인트로, 실시간 데이터 화면, WHAT IF 분석 앱을 한 Azure Static Web Apps 사이트로 패키징합니다. 시작 흐름은 `/` 로그인 → 인증 후 `/2_intro` → `/quote-monitor` 실시간 데이터입니다. 기존 분석 앱도 `/app/*` 경로로 유지합니다. 데모 체험 주소는 제공하지 않습니다.

배포 파일만 확인할 때는 저장소 루트에서 `python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site`를 실행합니다. 실제 배포는 Azure CLI 로그인 후 `python3 apps/web/quote-monitor/deploy.py`로 실행하고, 대상 기본 호스트가 서비스 주소와 일치하는지 먼저 확인합니다.
