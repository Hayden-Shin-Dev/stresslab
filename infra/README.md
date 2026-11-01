# Azure 인프라

리소스 담당의 작업 폴더입니다. Container Apps, Event Hubs, Functions, PostgreSQL, Web PubSub, Service Bus, API Management, ACR, 네트워크와 NAT, Key Vault, 인증 및 관측 설정을 관리합니다. Fabric 연결과 Capacity 설정도 이곳에서 관리하되 내부 처리 코드는 fabric에 둡니다. 이 저장소 생성 작업으로 실제 리소스를 변경하지 않았습니다.

| 폴더 | 내용 |
| --- | --- |
| [modules](modules/) | 재사용 가능한 리소스 정의. IaC 도구는 담당자가 선택 |
| [environments](environments/) | 개발 및 운영 설정. 비밀값 제외 |
| [deploy](deploy/) | 서비스 배포, 모델 승인, 버전 교체와 복구 절차 |
