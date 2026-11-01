# 키움 시세 입력

수집 담당이 Event Hubs로 보내고 Fabric 2가 Eventstream에서 받아. 한 메시지는 한 종목 관측값이고 형식은 JSON이야. Lakehouse 테이블 전달 형식과는 달라.

[quote-event.json](quote-event.json)은 합성 예시야. 그대로 운영 데이터에 넣으면 안 돼.

가격은 원, 거래량은 주. cumulative_volume은 세션 누적량이고 trade_volume은 해당 체결량이야. REST 조회에는 trade_volume을 NULL로 둬. event_id로 중복을 제거하고 event_time 순서로 처리해. provider_event_id가 없으면 수집기가 재전송에도 유지되는 ID를 만들어.

공급자가 날짜 없이 시각만 주면 date_inferred=true로 남겨. 거래소나 세션을 확인하지 못하면 UNKNOWN/unknown으로 두고 정규장 검증 데이터에 포함하지 마. REST의 수신시각을 체결시각으로 쓰지 마.

event_time이 NULL이면 시각 검증 불가야. 신선도는 기준시각-event_time으로 판단하고 received_at과 따로 보존해. 정규장 여부는 trading_calendar와 venue/session으로 확인해. 초기 허용 지연은 120초이며 운영 검증 후 조정해.

타입과 필수값은 [quote-event.schema.json](quote-event.schema.json)에 정의했어. is_mock=true 메시지는 운영 집계에서 제외해.
