# WHAT IF 랜딩 인트로

웹사이트 인트로의 단일 작업 폴더입니다. HTML, 스타일, 스크립트, 미리보기 서버를 이 위치에서 함께 관리합니다.

## 파일

- `index.html`: 인트로 화면
- `2_style.css`, `1_skin.css`: 기본 레이아웃과 스킨 스타일
- `2_script.js`: 화면 동작
- `preview_server.js`: 저장소 루트 기준 3000포트 미리보기 서버

## 로컬 확인

저장소 루트에서 실행합니다.

```powershell
node apps/web/0.web_main/preview_server.js
```
- 서비스 링크: https://red-field-0b8ece310.1.azurestaticapps.net/
- 공개 소개 화면: `http://localhost:3000/`
- 로그인: `http://localhost:3000/login`
- 워크스페이스: `http://localhost:3000/app` (실제 로그인은 Azure 배포에서 필요)
- 이 설명서: `http://localhost:3000/apps/web/0.web_main/README.md`
- 기존 WebGL 모션 데모: `http://localhost:3000/apps/web/motion-demo/`

## 배포

`apps/web/quote-monitor/deploy.py`는 이 폴더의 소개 화면과 로그인·공통 메뉴, 기존 분석 화면을 한 Azure Static Web Apps 사이트로 배포합니다. 로그인 뒤 `/app` 대시보드에서 기능별 주소로 이동합니다. 기존 `/quote-monitor`, `/quote-monito`, `/market.html` 주소는 `/app/market`으로 이어집니다. 데모 체험 주소는 제공하지 않습니다.

배포 파일만 확인할 때는 저장소 루트에서 `python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site`를 실행합니다. 실제 배포는 Azure CLI 로그인 후 `python3 apps/web/quote-monitor/deploy.py`로 실행하고, 대상 기본 호스트가 서비스 주소와 일치하는지 먼저 확인합니다.
