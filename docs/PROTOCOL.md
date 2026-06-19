# NBPowen / NBPower EV Charger — BLE Protocol Documentation

Reverse-engineered from `app-service.js` (uni-app bundle, v2.0.15).

---

## BLE Connection

| Parameter | Value |
|---|---|
| Service UUID (notify+write) | содержит `FFE0` |
| Characteristic UUID | содержит `FFE1` или `FFD1` |
| Alt service UUID (no notify) | содержит `FFD0` (noNotify=true) |
| Extra service UUID | содержит `FFC0` |

Логика подключения:
1. `createBLEConnection(deviceId)`
2. `getBLEDeviceServices` → ищем UUID с `FFE0` (или `FFD0`)
3. `getBLEDeviceCharacteristics(serviceId)` → ищем UUID с `FFE1` или `FFD1`
4. `notifyBLECharacteristicValueChange(characteristicId)` — подписываемся на уведомления
5. Всё готово к работе

---

## Packet Format

### Отправка (write to characteristic):
```
[ CMD, REQ_ID, param1, param2, ... ]
```

### Получение (notify):
```
[ CMD, REQ_ID, data1, data2, ... ]
```

Матчинг ответа: `response[0] == sent[0] && response[1] == sent[1]`  
`REQ_ID` — счётчик 0–255, автоинкремент при каждом запросе.

**Нет контрольной суммы!** Протокол простой — байты без CRC/XOR.

---

## Command Reference

### CMD 1 — Get Device Version
```
Send:  [0x01, req_id]
Recv:  [0x01, req_id, version, deviceNum, meterLen, runMode, chargerFuns, disabledFuns, gunCount]
```
- `version` — версия прошивки
- `deviceNum` — модель устройства (30=DC, иные=AC)

---

### CMD 49 (0x31) — Heartbeat / Status ⭐
```
Send:  [0x31, req_id, 0x01]
Recv:  [0x31, req_id, chargeState, temp1_raw, temp3_raw, pwmRange, _, _, cpCheckValid, cpCheckDelay, _, keyState, ...]
```

Разбор ответа:
| Байт | Поле | Формула |
|---|---|---|
| r[0] | `chargeState` | см. таблицу состояний |
| r[1] | `temp1` (°C) | `r[1] == 255 ? 255 : r[1] - 40` |
| r[2] | `temp3` (°C) | `r[2] == 255 ? 255 : r[2] - 40` |
| r[3] | `current` (A) | `pwmRange / 250 * 60` (см. ниже) |
| r[4] | `temp2` (°C) | `r[4] == 255 ? 255 : r[4] - 40` |
| r[5] | error code byte1 | |
| r[6..7] | error code (16bit) | `r[6] << 8 | r[7]` |
| r[8] | `cpCheckValid` | `r[8] == 1` |
| r[9] | `cpCheckDelay` | |
| r[10] | `keyState` | |
| r[15] | `temp4` (°C) | `r[15] == 255 ? 255 : r[15] - 40` |
| r[16] | `useElectricityPhase` | (if deviceVersion > 27) |

**Charge State Values (r[0]):**
| Значение | Состояние |
|---|---|
| 0 | Plug not inserted into vehicle |
| 1 | Car not started |
| 2 | In timing... (scheduled) |
| 3 | Charging... |
| 4 | Half Charging (reduced power) |
| 5 | Wait for cooling |
| 255 | Firmware update in progress |

---

### CMD 8 — Get Meter Data (V, A, P, kWh) ⭐
```
Send:  [0x08, req_id]
Recv:  [0x08, req_id, ...meter_bytes]
```

Разбор `meter_bytes` зависит от `deviceVersion`:

**deviceVersion > 27 (новые устройства):**
```
V   = (bytes[0] << 8 | bytes[1]) / 10      # Вольты
A   = (bytes[2] << 8 | bytes[3]) / 10      # Амперы
P   = V * A                                  # Мощность (Вт)
PValid = bytes[4] << 8 | bytes[5]           # Активная мощность (Вт)
KWH = (bytes[6] << 8 | bytes[7]) / 100     # кВт·ч
PFC = PValid / P * 100                      # Коэффициент мощности (%)
```

**deviceVersion <= 27 (старые устройства):**
```
V   = (bytes[1] << 8 | bytes[2]) / 10
A   = (bytes[3] << 8 | bytes[4]) / 10
PReg = bytes[5] << 16 | bytes[6] << 8 | bytes[7]
PValid = (bytes[8] << 8 | bytes[9]) / (deviceVersion > 17 ? 1 : 10)
g = bytes[10] << 8 | bytes[11]
m = bytes[12] << 8 | bytes[13]
eachKwhPFCount = floor(3600000000000 / (1.88 * PReg * 2))
KWH = (65536 * g + m) / eachKwhPFCount
```

> Для нескольких фаз: CMD 13, 14, 15 — такой же формат.

---

### CMD 67 (0x43) — Start Charging ⭐
```
Send:  [0x43, req_id, l[0]..l[12]]
```

Параметры `l[]`:
| Байт | Значение |
|---|---|
| l[0..5] | Токен безопасности (из CMD 66, или `[1,1,1,1,1,0]` если без токена) |
| l[6..7] | Минуты зарядки big-endian (`minutes >> 8`, `minutes & 0xFF`), 0=без ограничения |
| l[8..9] | Минуты задержки big-endian |
| l[10] | PWM Range = `round(250 * amps / 60)` |
| l[11..12] | (только DC) Напряжение * 10, big-endian |

Ответ: `[0x43, req_id, result, minutes_hi, minutes_lo, ...]`
- `result < 2 && minutes != 0` → ошибка (result содержит код)
- Иначе → успешно

---

### CMD 68 или CMD 49 с 0 — Stop Charging
```
Send:  [0x31, req_id, 0x00]    # stopCharge через heartbeat с параметром 0
```
*(Точный стоп-команды нет в открытом виде, вероятно через sendCommand с chargeState=0)*

---

### CMD 69 (0x45) — Get Charging Time
```
Send:  [0x45, req_id]
Recv:  [0x45, req_id, state, time_hi, time_lo, delay_hi, delay_lo, countdown_hi, countdown_lo]
```
- `state > 1` → зарядка идёт, `time = r[1]<<8|r[2]` мин, `countdown = r[6]<<8|r[7]` мин

---

### CMD 16 (0x10) — Reboot Device
```
Send:  [0x10, req_id]
```

---

### CMD 11 (0x0B) — Network / 4G Status
```
Send:  [0x0B, req_id, 0x00]
Recv:  [0x0B, req_id, len, net_byte, wan_byte, sim_byte, operator, ...]
```

---

### CMD 81 (0x51) — WiFi Settings
```
Send:  [0x51, req_id, 0x05]   # scan
Recv:  список SSID
```

---

### Преобразование ток ↔ PWM
```python
def amp_to_pwm(amps: float) -> int:
    return round(250 * amps / 60)

def pwm_to_amp(pwm: int) -> float:
    raw = pwm / 250 * 60
    frac = raw % 1
    if 0.3 <= frac <= 0.7:
        frac = 0.5
    elif frac > 0.7:
        frac = 1.0
    else:
        frac = 0.0
    return int(raw) + frac
```

Диапазон тока: 6A–32A (PWM 25–133).

---

## Polling Strategy для Home Assistant

| Команда | Интервал | Данные |
|---|---|---|
| CMD 49 | 3–9 сек | Состояние, температура, ток |
| CMD 8 | 5–10 сек | Вольты, амперы, мощность, кВт·ч |
| CMD 69 | 10 сек | Время зарядки |
