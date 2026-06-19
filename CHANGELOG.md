# Changelog

## [1.2.0] - 2025-XX-XX

### Added — network status sensors
- WiFi state (off / disconnected / no_network / connected) — text label
- WiFi RSSI signal level (0-3 bars)
- Cellular network mode (4G / 3G / 2G / no signal)
- Cellular RSSI (0-5 bars)
- Network operator name
- SIM card presence flag (in attributes)
- 4G modem availability flag
- All powered by CMD 11 (network status command)

## [1.1.0] - 2025-XX-XX

### Added — extended sensor set from app
- **Last session info** (CMD 50): kWh, duration, max temperature, min voltage, requested current, stop reason (19 types)
- **Lifetime totals** (CMD 43): total energy, total session count
- Slow-poll mechanism: heavy data fetched every 6 cycles

## [1.0.1] - 2025-XX-XX

### Fixed
- Config flow: MAC auto-populated from Bluetooth discovery
- Removed max_amps from initial config flow

## [1.0.0] - 2025-XX-XX

### Added
- Initial release with full BLE protocol support
