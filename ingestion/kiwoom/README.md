# 키움 실시간 수집

`ca-kiwoom-collector-dev`에서 상시 실행합니다. 키움 체결을 받아 `evh-whatif-dev`로 전송합니다. 파티션 키는 `asset_id`입니다. 기존 2개 파티션은 유지합니다.

| 파일 | 역할 |
| --- | --- |
| collector.py | 인증, 체결 수신, 전송, 재연결, 상태 기록 |
| universe.json | KRX 시가총액 기준 코스피 개별 주식 20종목과 선정 기준일 |
| Dockerfile | Azure 실행 이미지 |

현재 한 연결에서 20종목을 구독합니다. 키움 한도는 200종목이며, 확대용 목록은 universe_200.json에 보존합니다. 코스피 전체나 공식 코스피200 구성종목을 뜻하지 않습니다. 종목 목록은 기준일이 있는 고정 목록이며 자동 교체하지 않습니다.

MODE=stream으로 실행합니다. 키움 키는 기존 앱 비밀 설정을 사용합니다. 연결이 끊기면 재접속하고 전체 목록을 다시 구독합니다. 체결이 없는 시간에도 프로세스는 유지합니다.

JSON 본문은 `contracts/realtime/schema.json`을 따릅니다. 공급자 원문은 Event Hubs 메시지 속성 `provider_raw`에 보존합니다. 날짜는 수신일로 추정하므로 `date_inferred=true`를 유지합니다. 확인되지 않은 거래소와 세션은 unknown으로 전달합니다.

전송 실패 시 같은 event_id로 재시도합니다. Fabric은 event_id로 중복을 제거해야 합니다. 30초마다 수신 건수, 종목 수, 전송 건수, 대기 건수와 연결 상태를 로그에 남깁니다.

미전송 체결은 컨테이너 내부 SQLite에 임시 보관합니다. 컨테이너 교체 시 이 저장소는 유지되지 않습니다. 연결 중단 구간의 체결도 자동 복원되지 않습니다. Event Hubs 이후 영구 적재는 Fabric에서 처리합니다.

## 거래 세션 분류

sessions.py에서 공급자 체결 시각(20), 거래소(9081), 장구분(290)을 함께 확인합니다. 수신 시각으로 세션을 정하지 않습니다. 290=2를 무조건 정규장으로 바꾸지 않습니다.

KRX는 2026-09-14부터 16:00~20:00 애프터마켓을 운영합니다. 해당 구간 체결은 본문의 session=afterhours, 메시지 속성의 session_detail=krx_aftermarket으로 전달합니다. 기존 시간외 단일가는 시행일 이전 자료에서만 구분합니다. 시간외 종가와 NXT 프리/메인/애프터마켓도 별도로 분류합니다.

본문 스키마는 그대로입니다. 상세 구분과 사유는 Event Hubs 속성 session_detail, session_reason, session_rule_version에 기록합니다. provider_raw와 함께 보존하세요. 분류 불가 사유는 session_unclassified 로그와 30초 상태 로그의 session_unknown_reasons에 남깁니다.

규칙은 일반 거래시간 기준이며 특별 개장일과 휴장일을 인증하는 거래 달력은 아닙니다. date_inferred=true를 유지합니다. KRX 종가 동시호가 시간 구분도 개별 체결 방식의 직접 인증과 다릅니다. VI 등 개별 체결 방식은 이 시세 메시지만으로 단정하지 않습니다.

근거: [KRX 거래시간](https://regulation.krx.co.kr/contents/RGL/03/03010100/RGL03010100T1.jsp), [KRX 애프터마켓](https://regulation.krx.co.kr/contents/RGL/03/03010301/RGL03010301.jsp), [시행일과 시간외단일가 폐지](https://securities.miraeasset.com/bbs/board/message/view.do?body=Y&categoryId=66&messageId=2342552&selectedId=1000000202&selectedId=1000000203), [키움 공식 API 명세](https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/kiwoom/_data/kiwoom_api_spec.json).
