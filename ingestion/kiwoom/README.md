# 키움 시세 수집

키움 실제 체결을 받아 Event Hubs로 전달합니다. VS Code에서 작업하고 Azure Container Apps에서 실행합니다.

| 파일 | 역할 |
| --- | --- |
| collector.py | 출구 IP 확인, 키움 연결, 시세 전송 |
| requirements.txt | 필요한 Python 라이브러리 |
| Dockerfile | Azure 실행 이미지 구성 |

MODE=probe는 출구 IP 확인, MODE=stream은 실제 수집입니다. 키움 키는 Azure 비밀 설정에 저장합니다.

현재는 삼성전자·현대차 2종목 연결 시험용입니다. 날짜·세션 인증과 영구 저장은 운영 적용 전 보완해야 합니다.
