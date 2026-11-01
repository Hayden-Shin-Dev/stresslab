# 서비스

각 하위 폴더는 별도 실행 서비스의 경계입니다. 실제 배포 단위는 부하와 운영 비용을 확인한 뒤 결정합니다. API 계약은 contracts에서 공유하고 서비스 간 코드를 복사하지 않습니다.

| 폴더 | 내용 |
| --- | --- |
| [api](api/) | 공통 API |
| [stress-engine](stress-engine/) | 스트레스 엔진 |
| [market-state](market-state/) | 시장 상태 API |
| [quote-updater](quote-updater/) | 현재가 갱신 |
| [debate](debate/) | AI 토론 실행기 |
| [tools](tools/) | AI 도구 API |
