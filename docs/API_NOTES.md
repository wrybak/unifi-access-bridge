# API Notes

## UniFi Access
- sterowanie drzwiami i statusy: Access OpenAPI
- push updates: WebSocket
- miniatury: Access static/thumbnail path

## UniFi Protect
- jeśli kamera ma istniejącą encję `camera.*` w Home Assistant, używamy jej jako źródła live preview
- nie wymagamy osobnego logowania do Protect w MVP

## Porty
W materiałach Ubiquiti występuje niespójność:
- 12445
- 12455

W implementacji trzeba:
- umożliwić ręczne ustawienie portu,
- dodać auto-probe.
