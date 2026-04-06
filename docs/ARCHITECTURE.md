# Architektura

## 1. Warstwy

### 1.1 Access layer
Odpowiada za:
- autoryzację tokenem,
- pobieranie listy drzwi,
- unlock,
- WebSocket events,
- pobieranie miniaturek.

### 1.2 Domain layer
Normalizuje dane do własnych modeli:
- `DoorState`
- `CameraMapping`
- `DoorEventPayload`

### 1.3 Home Assistant layer
Publikuje encje:
- button
- binary_sensor
- event
- camera

## 2. Źródła obrazu

### HA camera proxy
Najbezpieczniejszy wariant.
Nie logujemy się osobno do Protect.
Wykorzystujemy już istniejącą encję `camera.*`.

### RTSP/RTSPS
Wariant dla kamer dostępnych po stream URL.

### Snapshot fallback
Minimalny i stabilny fallback dla sytuacji, gdy live video nie da się uzyskać.

## 3. Dlaczego nie „wszystko przez Access”
Access jest idealny do sterowania drzwiami, ale projekt nie może zakładać,
że live stream będzie zawsze dostępny i stabilny przez jego API.
Dlatego źródło sterowania i źródło obrazu są rozdzielone.

## 4. Rozszerzenia
- auto-discovery mapowania po nazwach,
- import mapowania z OpenAPI / device export,
- custom Lovelace card.
