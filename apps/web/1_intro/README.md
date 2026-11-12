# WHAT IF 인트로

이 폴더가 WHAT IF 웹사이트 인트로의 운영 소스입니다. 랜딩 화면 파일은 `0_main`의 디자인을 가져와 이 경로에서 수정하고 배포합니다. 기존 WebGL 모션 데모는 `apps/web/motion-demo`에 보존되어 있습니다.

## 파일

- `index.html`: 랜딩 화면
- `2_style.css`, `1_skin.css`: 레이아웃과 시각 스타일
- `2_script.js`: 페이지 상호작용
- `preview_server.js`: 저장소 루트 기준 로컬 미리보기 서버

## 로컬 확인

저장소 루트에서 실행합니다.

```powershell
node apps/web/1_intro/preview_server.js
```

- 인트로: `http://localhost:3000/apps/web/1_intro/`
- 이 설명서: `http://localhost:3000/apps/web/1_intro/README.md`
- 기존 모션 데모: `http://localhost:3000/apps/web/motion-demo/`

## 배포

`apps/web/quote-monitor/deploy.py`는 이 폴더를 웹사이트의 홈과 `/dlsxmfh` 경로로 배포합니다. 기존 실시간 화면은 `/quote-monitor`와 `/market.html`에서 이용할 수 있습니다.
