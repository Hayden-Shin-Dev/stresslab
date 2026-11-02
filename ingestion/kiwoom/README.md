# Azure 키움 수집기 연결 시험

NAT 없이 삼성전자와 현대차 실제 체결을 Event Hubs로 보내는 코드입니다. 주문과 계좌 조회는 하지 않습니다. 처음에는 출구 IP 확인만 실행하고, 키움에 IP를 등록한 뒤 실제 수집을 켭니다.

## 1. Cloud Shell 열기

Azure Portal 상단의 Cloud Shell 아이콘을 누르고 Bash를 선택하세요. 저장소 연결 없이 사용하는 옵션이 있으면 선택해도 됩니다. 터미널에서 다음을 실행합니다.

```bash
git clone https://github.com/Hayden-Shin-Dev/stresslab.git
cd stresslab
az extension add --name containerapp --upgrade
bash ingestion/kiwoom/01-deploy-probe.sh
```

이미 이 저장소를 받은 상태라면 해당 폴더에서 `git pull --ff-only` 후 실행하세요. 코드 수정 없이 그대로 실행할 수 있습니다. 실행 전에 아래 생성 범위를 확인하세요.

| 항목 | 값 |
| --- | --- |
| 기존 리소스 그룹 | 5dt-final-team3 |
| 기존 Container Apps 환경 | cae-whatif-dev |
| 기존 레지스트리 | acrwhatifdev5dt |
| 기존 전송 대상 | evhns-whatif-dev / evh-whatif-dev |
| 새 수집기 앱 | ca-kiwoom-collector-dev |
| 새 관리 ID | id-kiwoom-collector-dev |
| 관리 ID 권한 | 해당 ACR의 AcrPull, 해당 Event Hub의 Azure Event Hubs Data Sender |

스크립트는 이미지를 빌드하고 수집기 앱을 생성합니다. 기존 ca-whatif-dev 앱과 NAT 설정은 변경하지 않습니다. 수집기는 외부 웹 접속 없이 1개 인스턴스로 실행합니다. NAT 비용은 없지만 이미지 빌드·앱·레지스트리·로그 등 기존 Azure 사용 요금은 별도입니다.

## 2. 실제 출구 IP 확인

```bash
source ingestion/kiwoom/azure-env.sh
az containerapp logs show -g "$SL_RG" -n "$SL_APP" --type console --tail 30 --follow
```

`egress_ip_observed`의 `ip`를 확인하고 Ctrl+C로 로그 조회만 종료합니다. 앱은 계속 실행됩니다. 이 IP를 키움 REST API 앱의 허용 IP에 등록하세요. Cloud Shell 자체의 IP를 등록하면 안 됩니다. 진단 사이트에서 관측한 출구 IP이며 키움에서도 같은 경로인지 인증 성공으로 추가 확인합니다. NAT가 없으므로 향후 고정은 보장되지 않습니다.

## 3. 키움 키 저장

Azure Portal → 리소스 그룹 `5dt-final-team3` → Container App `ca-kiwoom-collector-dev` → 설정의 **비밀 / Secrets** → **추가**에서 아래 두 개를 저장하세요.

| 비밀 이름 | 값 |
| --- | --- |
| kiwoom-app-key | 실제 키움 REST 앱 키 |
| kiwoom-secret-key | 실제 키움 REST 시크릿 키 |

직접 입력 방식으로 저장합니다. 키를 GitHub, 코드, 터미널 명령에 넣지 마세요. 이번 시험에서는 Container Apps 비밀을 사용하며 Event Hubs 인증은 관리 ID로 처리합니다.

## 4. 실제 수집 켜기

키움 IP 등록과 비밀 저장이 끝나면 Cloud Shell에서 실행하세요.

```bash
bash ingestion/kiwoom/02-start-stream.sh
```

순서대로 `kiwoom_token_ok`, `kiwoom_login_ok`, `kiwoom_subscribed`가 나와야 합니다. 실제 체결을 받아 Event Hubs가 전송을 확인하면 `eventhub_sent`와 누적 전송 수가 나옵니다. 장외에는 로그인과 구독만 성공하고 체결은 없을 수 있습니다. 이를 수신 성공으로 판단하지 않습니다.

## 5. Fabric 담당과 확인

전달 대상은 `evhns-whatif-dev.servicebus.windows.net`의 `evh-whatif-dev`입니다. Fabric 담당은 별도 소비자 그룹과 수신 권한으로 Eventstream을 연결합니다. 전송기에는 수신 권한이 없습니다.

`quote_event v1`이며 종목 코드는 005930, 005380입니다. is_mock=false이지만 날짜는 시각에서 추정하므로 date_inferred=true, venue=UNKNOWN, session=unknown입니다. 원본 수신 경로에서 확인하고 정규장 검증 집계에는 아직 포함하지 마세요. 날짜·세션 인증을 완료한 운영 수집기와 구분합니다.

Azure Portal → Event Hubs 네임스페이스 → 모니터링 → 메트릭에서 Incoming Messages를 확인하고, Fabric에서도 실제 메시지의 event_id와 시각을 확인하세요. 메트릭만 증가했다고 Fabric 분석까지 완료된 것은 아닙니다.

## 오류와 시험 종료

| 로그 또는 오류 | 확인할 내용 |
| --- | --- |
| AuthorizationFailed | 실행 계정의 리소스 생성·역할 할당 권한을 유진 담당에게 요청 |
| 이미지 가져오기 실패 | AcrPull 권한 반영 후 재시도, ACR 접근 설정 확인 |
| egress_probe_failed | 앱에서 외부 HTTPS 통신이 가능한지 확인 |
| kiwoom_auth_failed | 허용 IP, 키, 실전 API 사용 여부 확인. 반환 코드로 원인 구분 |
| kiwoom_reconnecting | 네트워크 또는 WebSocket 로그인·구독 상태 확인 |
| eventhub_retry | Data Sender 권한 반영과 Event Hubs 접근 설정 확인 |

시험을 중단할 때는 다음을 실행하세요. 앱 중지만으로 레지스트리 등 다른 리소스 비용이 사라지지는 않습니다.

```bash
source ingestion/kiwoom/azure-env.sh
for revision in $(az containerapp revision list -g "$SL_RG" -n "$SL_APP" --query "[?properties.active].name" -o tsv); do
  az containerapp revision deactivate -g "$SL_RG" -n "$SL_APP" --revision "$revision"
done
```

이 코드는 연결 시험용입니다. 전송 실패 건은 SQLite에 같은 event_id로 보관해 재시도하지만 컨테이너 교체 시 임시 디스크가 사라질 수 있습니다. 공급자 재수신의 동일 체결 판별, 영구 원문 저장, 누락 복구, 날짜·세션 인증과 종목 확대는 운영 단계에서 추가 검증해야 합니다. 로컬 코드 검사는 실제 Azure·키움 접속 성공을 대신하지 않습니다.
