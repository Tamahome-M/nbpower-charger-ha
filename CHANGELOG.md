# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2025-XX-XX

### Added
- Initial release
- BLE protocol reverse-engineered from NBPowen app v2.0.15
- Support for FFD0 (polling) and FFE0 (notify) BLE service modes
- 10+ sensors (voltage, current, power, energy, temperature, charge state, timers)
- Switch entity for start/stop charging
- Number entity for adjustable max current (6-32 A)
- Auto-discovery via Bluetooth
- Config flow with MAC address input
- Russian and English translations
- Standalone debug script (`scripts/nbpower_debug.py`)
- Tested with firmware v45, device_num=31 (AC charger)

### Protocol Details
- Auth challenge mechanism for charge start (CMD 66 → CMD 67)
- Polling-mode reads from same characteristic as writes (FFD1)
- 20ms minimum delay between BLE writes
- Support for both write-with-response and write-without-response modes
