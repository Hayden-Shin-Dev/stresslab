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
- 서비스 링크 : https://red-field-0b8ece310.1.azurestaticapps.net/quote-monitor
- 인트로: `http://localhost:3000/apps/web/0.web_main/`
- 이 설명서: `http://localhost:3000/apps/web/0.web_main/README.md`
- 기존 WebGL 모션 데모: `http://localhost:3000/apps/web/motion-demo/`

## 배포

`apps/web/quote-monitor/deploy.py`는 이 폴더를 사이트 홈 및 `/dlsxmfh` 경로로 배포합니다. 기존 실시간 화면은 `/quote-monitor`와 `/market.html`에 유지됩니다.
