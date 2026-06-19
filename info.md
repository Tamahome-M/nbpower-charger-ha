# NBPower EV Charger (BLE)

Local Bluetooth control for **NBPower / NBPowen** electric vehicle chargers
in Home Assistant — no cloud, no account required.

## What you get

- **10+ sensors**: voltage, current, power, energy (kWh), temperature, charge state
- **Start/Stop switch** — full charging control
- **Adjustable current limit** (6–32 A) via slider
- **Auto-discovery** via Bluetooth

## Quick Setup

1. Install via HACS
2. Restart Home Assistant
3. Settings → Devices & Services → Add **NBPower EV Charger**
4. Enter MAC address from the NBPowen app (or scan with nRF Connect)

See [README](https://github.com/Tamahome-M/nbpower-charger-ha) for full documentation.

## Compatibility

Tested with firmware v45, device_num=31 (AC charger).
Should work with most NBPower AC and DC chargers managed by the NBPowen app
(package `uni.app.UNIC8204CB`).

Built using reverse engineering — no affiliation with the manufacturer.
