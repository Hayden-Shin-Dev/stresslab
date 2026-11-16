# WHAT IF 웹 서비스

이 폴더에는 로컬 미리보기 서버와 이력 문서만 남아 있습니다. 배포되는 화면 파일은 모두 [`apps/web/quote-monitor/site`](../quote-monitor/site)로 이동했습니다.

## 로컬 확인

저장소 루트에서 실행합니다.

```sh
node apps/web/0.web_main/preview_server.js
```

- 서비스 링크: https://red-field-0b8ece310.1.azurestaticapps.net/
- 첫 화면/로그인: `http://localhost:3000/` 또는 `http://localhost:3000/login`
- 로그인 후 2차 인트로: `http://localhost:3000/2_intro`
- 실시간 데이터: `http://localhost:3000/quote-monitor`
- 워크스페이스: `http://localhost:3000/app` (실제 로그인은 Azure 배포에서 필요)

## 배포

배포할 정적 파일 전체는 `apps/web/quote-monitor/site/`에 모여 있습니다. `apps/web/quote-monitor/deploy-manifest.json`은 9개 핵심 파일과 필수 페이지·자산을 기록하고, `deploy.py`는 해당 디렉터리 하나를 빌드·배포합니다.

```sh
python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
```

실제 배포는 Azure 인증과 배포 토큰이 준비된 뒤 같은 스크립트로 진행합니다.
