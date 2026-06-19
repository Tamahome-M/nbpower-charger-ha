# Changelog

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
