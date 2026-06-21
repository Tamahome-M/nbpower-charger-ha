# Changelog

## [1.7.0]

### Added — full feature parity with the app
- **Change PIN** service (`nbpower_charger.change_password`) — CMD 51
- **Configure WiFi** service (`nbpower_charger.configure_wifi`) — set SSID + password, CMD 81
- **Set run mode** service (`nbpower_charger.set_run_mode`) — alternative to the select entity
- **Reboot** button — CMD 16
- **Reset total energy counter** button (hidden by default) — CMD 44
- Debug script: `--change-pwd`, `--set-wifi`, `--reboot` commands
- All new services are PIN-protected and resolve the target via the HA device picker

### Notes
This release aims for full Bluetooth feature parity with the NBPowen app. Remaining app-only items are factory/calibration commands (CMD 7), IC-card management (CMD 253), and DC/BMS telemetry (CMD 145/146) which are niche and hardware-specific.

## [1.6.0]

### Added
- **Bluetooth signal strength** sensor (dBm) — reads the BLE RSSI from the Home Assistant Bluetooth stack (no extra request to the charger). Useful for diagnosing connection quality and ESPHome proxy placement. Listed under diagnostics.

## [1.5.1]

### Fixed
- **CMD 47 (read config) requires the device PIN** — without prior password verification the charger returns an empty response. Now `get_charger_config` verifies the PIN first (CMD 41), so run mode / max amps / temps read correctly.
- Debug script: `--config` and `--set-mode` now verify the PIN (use `--pwd`).

### Confirmed working (manual BLE test)
- Start charging: PIN → challenge → token → CMD 67 → state changes to "charging" ✅
- Stop charging: PIN → CMD 67 (minutes=0) → state changes to "standby" ✅

## [1.5.0]

### Added — run mode (plug-and-charge) control
- New **"Режим работы"** select entity with three options:
  - Управление из приложения (mobile control)
  - **Зарядка с вилки (авто)** — charging starts automatically when the cable is plugged in
  - Запуск ключом (key switch)
- Reads/writes the full device config via CMD 47 (read) and CMD 48 (write), changing only the run-mode byte while preserving all other settings. Requires device PIN.
- New binary sensors:
  - "Зарядка с вилки включена" — whether plug-start mode is active
  - "Идёт зарядка" (battery charging)
  - "Кабель подключён" (plug)
  - "Авто-возобновление" (hidden by default) — resume charging after power loss
- Config (run mode, max amps, temps, auto-recharge) is now refreshed on each slow-poll cycle.
- Debug script: `--config` to read configuration, `--set-mode {0,1,2}` to change run mode.

## [1.4.0]

### Added — device password (PIN) support
- The charger verifies a device PIN (CMD 41) before allowing start/stop charging — confirmed by testing (correct PIN → accepted, wrong PIN → rejected).
- New **"Пароль устройства (PIN)"** field in config flow (Bluetooth confirm + manual entry), default `000000`.
- Password can be changed later via **Settings → Devices → NBPower → Configure** (Options), applied live without reload.
- Password is verified before each charge start/stop, with a 9-second success cache (matching the NBPowen app behaviour).
- Debug script: `--pwd PWD` flag for start/stop, plus corrected `--test-pwd` (BLE format = 6 raw ASCII bytes, no prefix byte).

### Fixed
- Password verify command format for BLE: send 6 ASCII bytes directly (the leading `1` byte is only for network/IMEI mode, not BLE).

## [1.3.3]

### Fixed
- **Elapsed/remaining time parsing** (CMD 69): wrong byte offsets caused "Время зарядки" to show 65535 minutes (which is actually the *configured timer* meaning unlimited). Now correctly:
  - `data[1..2]` → configured timer (new sensor "Установленный таймер")
  - `data[3..4]` → elapsed minutes
  - `data[6..7]` → remaining minutes (unchanged)

### Added
- "Установленный таймер" sensor (hidden by default) — shows the duration set when charging started, 0 = unlimited

## [1.3.2]

### Fixed
- When CMD 49 (heartbeat) returns no/short response (BLE timeout, broken connection), entity values previously fell back to defaults (charge_state=0 → "Кабель не подключён"). Now they preserve the last known good values until the next successful poll.
- Added detailed DEBUG logs of raw status (charge_state, voltage, current, kWh) for easier diagnostics. Enable with:
  ```yaml
  logger:
    logs:
      custom_components.nbpower_charger: debug
  ```

## [1.3.1]

### Fixed
- Voltage now displayed with 1 decimal (e.g. 241.1 V instead of 241 V)
- Current displayed with 2 decimals, energy with 2-3 decimals — consistent precision across all electrical sensors

## [1.3.0]

### Fixed — max charging current behaviour
- Slider step changed from 1 A to **0.5 A** to support values like 9.5 A
- Slider max value now reflects the actual hardware limit (CMD 47), not hardcoded 32 A
- Initial slider value is seeded from the **last session's requested current** (instead of hardcoded 16 A) — matches what the NBPowen app shows
- Slider changes persist across HA restarts via config entry options
- Changing the slider no longer triggers a full integration reload; applies live and (if charging) immediately re-issues start with the new current

### Added
- New static config dataclass (`NBPowerChargerConfig`) for hardware limits and 50/60 Hz
- `get_charger_config()` BLE method (CMD 47)

## [1.2.0]

### Added — network status sensors
- WiFi state (off / disconnected / no_network / connected) — text label
- WiFi RSSI signal level (0-3 bars)
- Cellular network mode (4G / 3G / 2G / no signal)
- Cellular RSSI (0-5 bars)
- Network operator name
- SIM card presence flag (in attributes)
- 4G modem availability flag
- All powered by CMD 11 (network status command)

## [1.1.0]

### Added — extended sensor set from app
- **Last session info** (CMD 50): kWh, duration, max temperature, min voltage, requested current, stop reason (19 types)
- **Lifetime totals** (CMD 43): total energy, total session count
- Slow-poll mechanism: heavy data fetched every 6 cycles

## [1.0.1]

### Fixed
- Config flow: MAC auto-populated from Bluetooth discovery
- Removed max_amps from initial config flow

## [1.0.0]

### Added
- Initial release with full BLE protocol support
