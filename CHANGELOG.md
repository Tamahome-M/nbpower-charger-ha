# Changelog

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
