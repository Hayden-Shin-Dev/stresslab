# WHAT IF V6 local development

V6 화면을 StressLab 배포 원본과 분리해 수정하고 확인하는 작업 공간입니다. 실제 배포 입력 폴더는 `apps/web/quote-monitor/site/`이며, 개발 완료 후 `npm run promote`로 `site/whatif-v6/`에 빌드 결과를 복사합니다.

## 시작

Node.js 22 이상이 필요합니다. 의존성 설치는 없습니다.

```sh
cd apps/web/whatif-v6-dev
npm run dev
```

브라우저에서 `http://localhost:4213/whatif-v6/`를 엽니다. `source/src`, `source/assets`, `source/content`의 HTML, CSS, JS, JSON 또는 미디어 파일을 저장하면 자동으로 다시 빌드하고 브라우저를 새로고침합니다.

## 작업 구조

- `source/`: V6 원본 소스와 리소스. 이 폴더에서 수정합니다.
- `dist/whatif-v6/`: 미리보기용 생성물. Git에는 넣지 않습니다.
- `npm run promote`: 생성물을 StressLab의 배포 입력 폴더 `apps/web/quote-monitor/site/whatif-v6/`로 복사합니다.

로컬 시나리오 화면은 배포된 웹의 ‘실시간 데이터’와 같은 API 경로를 사용합니다: `/api/quotes/latest`, `/api/quotes/negotiate`, `/api/market-state/current`, `/api/market-state/negotiate`. 기본 API origin은 `https://red-field-0b8ece310.1.azurestaticapps.net`이며, 기존 화면과 동일하게 실제 quote와 시장 상태를 받아 종목 코드로 합칩니다. 개발 API 로그인에는 OAuth 클라이언트에 `http://localhost:4213/.auth/login/google/callback` redirect URI가 등록되어 있어야 합니다. 다른 API origin을 쓰려면 환경 변수로 지정합니다.

```sh
WHATIF_DEV_API_ORIGIN=https://<인증된-개발-API-호스트> npm run dev
```

프록시는 문서화된 로그인 경로와 시세 API 네 경로만 전달하며 로그인 쿠키를 전달합니다. 인증을 통과한 `is_mock: false` 시세만 표시합니다. 브라우저에 API 키를 넣거나 이 작업 공간의 비밀값을 커밋하지 마세요.

첨부 V6 폴더에서 가져온 것은 `src/`, `assets/`, `content/`, `build.mjs`와 아이콘·사운드 생성 스크립트입니다. 생성된 단독 HTML, `node_modules`, 실제 `.env`, QA 캡처·자료는 포함하지 않았습니다.
