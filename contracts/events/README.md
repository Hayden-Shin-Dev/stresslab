# 키움 시세 입력

수집 담당이 Event Hubs로 보내고 Fabric 2가 Eventstream에서 수신합니다. 한 메시지는 한 종목 관측값이고 형식은 JSON입니다. Lakehouse 테이블 전달 형식과는 다릅니다.

[quote-event.json](quote-event.json)은 합성 예시입니다. 운영 데이터에는 사용하지 않습니다.

가격 단위는 원, 거래량 단위는 주입니다. cumulative_volume은 세션 누적량이고 trade_volume은 해당 체결량입니다. REST 조회에는 trade_volume을 NULL로 저장합니다. event_id로 중복을 제거하고 event_time 순서로 처리합니다. provider_event_id가 없으면 수집기가 재전송에도 유지되는 ID를 생성합니다.

공급자가 날짜 없이 시각만 주면 date_inferred=true로 기록합니다. 거래소나 세션을 확인하지 못하면 UNKNOWN/unknown으로 두고 정규장 검증 데이터에 포함하지 않습니다. REST의 수신시각을 체결시각으로 사용하지 않습니다.

event_time이 NULL이면 시각을 검증할 수 없습니다. 신선도는 기준시각-event_time으로 판단하고 received_at과 따로 보존합니다. 정규장 여부는 trading_calendar와 venue/session으로 확인합니다. 초기 허용 지연은 120초이며 운영 검증 후 조정합니다.

타입과 필수값은 [quote-event.schema.json](quote-event.schema.json)에 정의했습니다. is_mock=true 메시지는 운영 집계에서 제외합니다.
