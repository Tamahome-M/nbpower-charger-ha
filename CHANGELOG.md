# Changelog

## [1.0.1] - 2025-XX-XX

### Fixed
- Config flow: when adding a Bluetooth-discovered charger, MAC is now auto-populated (was empty)
- Removed `max_amps` from initial config flow — it's now only in Options (default 16 A)
- Added separate steps for Bluetooth confirmation, picking from discovered devices, and manual MAC entry
- Improved translations for new flow steps

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
