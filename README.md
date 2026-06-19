# NBPower EV Charger — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/Tamahome-M/nbpower-charger-ha?include_prereleases)](https://github.com/Tamahome-M/nbpower-charger-ha/releases)

Custom Home Assistant integration for **NBPower / NBPowen** EV chargers
(manufactured by Hubei Mairuisi New Energy Technology Co., Ltd.) via **Bluetooth Low Energy**.

Works **locally** — no cloud connection required.

The integration was reverse-engineered from the [NBPowen Android app](https://play.google.com/store/apps/details?id=uni.app.UNIC8204CB) version 2.0.15.

## Features

### Sensors
| Sensor | Description |
|---|---|
| Charge state | Text status: "Unplugged", "Standby", "Charging"... |
| Voltage | Volts (V) |
| Current | Amperes (A) |
| Power | Watts (W) |
| Active Power | Real power consumption (W) |
| Energy (session) | kWh consumed in current charging session |
| Power factor | % |
| Temperature 1-4 | Internal temperature sensors (°C) |
| Elapsed time | Minutes since charging started |
| Remaining time | Minutes until timer expires (if set) |

### Controls
| Entity | Type | Description |
|---|---|---|
| Charging | Switch | Start / stop charging |
| Maximum current | Number (6–32 A) | Slider to set current limit |

## Supported Hardware

Tested on:
- NBPower AC charger, device_num=31, firmware v45

Should also work with:
- AC chargers reporting device_num: 26, 27, 28, 29, 31, 32, 33
- DC chargers (device_num=30) — limited support

If your device works, please [open an issue](../../issues) with the firmware version
and device_num so we can update the compatibility list.

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** → **Custom repositories**
3. Add: `https://github.com/Tamahome-M/nbpower-charger-ha` (Category: Integration)
4. Find **NBPower EV Charger (BLE)** and click **Download**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration**
7. Search for **NBPower EV Charger**

### Manual Installation

1. Copy `custom_components/nbpower_charger/` to your HA `/config/custom_components/`
2. Restart Home Assistant
3. Add the integration via UI

## Configuration

When you add the integration, you'll need to provide:
- **MAC address** of your charger (e.g. `F0:C7:7F:01:98:27`)
- **Name** (optional, defaults to "NBPower XXXXXXXX")
- **Poll interval** in seconds (3-60, default 5)
- **Default max current** in Amperes (6-32, default 16)

### Finding your charger's MAC address

**Option 1: Via nRF Connect app (Android/iOS)**
- Install [nRF Connect](https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp)
- Scan for BLE devices
- Look for a device named `NBPower-XXXXXXXXXXXX`
- The 12 hex chars after `NBPower-` are the MAC (insert colons)

**Option 2: From the NBPowen app**
- Open the app → Connect to your charger → Device Info → MAC Address

**Option 3: Linux command line** (using included debug script)
```bash
pip install bleak
python3 scripts/nbpower_debug.py --scan
```

## Bluetooth Requirements

This integration requires Home Assistant Bluetooth support:

### Local Bluetooth
- Built-in Bluetooth on Raspberry Pi
- USB Bluetooth dongle on x86 hosts
- Make sure HA can access `/dev/bluetooth` or the host's BlueZ

### ESPHome Bluetooth Proxy (recommended for distant chargers)

If your charger is in the garage and far from HA, use an ESP32 as a BLE proxy:

```yaml
# esp32_ble_proxy.yaml
esphome:
  name: ble-proxy-garage

esp32:
  board: esp32dev
  framework:
    type: esp-idf

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

bluetooth_proxy:
  active: true

api:
ota:
logger:
```

After flashing, HA will auto-discover the proxy and use it for BLE communication.

## Example Automations

### Charge only at night (cheap tariff)

```yaml
automation:
  - alias: "Start charging at night"
    trigger:
      - platform: time
        at: "23:00:00"
    condition:
      - condition: state
        entity_id: sensor.nbpower_charge_state
        state: "standby"
    action:
      - service: number.set_value
        target:
          entity_id: number.nbpower_max_current
        data:
          value: 10
      - service: switch.turn_on
        target:
          entity_id: switch.nbpower_charging

  - alias: "Stop charging in morning"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.nbpower_charging
```

### Notify when charging finishes

```yaml
automation:
  - alias: "Notify on charge complete"
    trigger:
      - platform: state
        entity_id: sensor.nbpower_charge_state
        from: "charging"
        to: "standby"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "EV Charging Complete"
          message: "Charged {{ states('sensor.nbpower_energy') }} kWh"
```

### Match solar production

```yaml
automation:
  - alias: "Match charger to solar"
    trigger:
      - platform: state
        entity_id: sensor.solar_power_excess
    condition:
      - condition: state
        entity_id: sensor.nbpower_charge_state
        state: "charging"
    action:
      - service: number.set_value
        target:
          entity_id: number.nbpower_max_current
        data:
          # 230V single phase. Cap between 6A and 32A.
          value: "{{ [[states('sensor.solar_power_excess')|float / 230, 6]|max, 32]|min }}"
```

## Protocol

The BLE protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md).
Key facts:

- BLE Service: `FFD0` (polling mode) or `FFE0` (notify mode)
- Characteristic: `FFD1` / `FFE1`
- Packet: `[CMD, REQ_ID, ...params]` — no checksum
- Polling: after each `write` on FFD1, read FFD1 to get response
- Auth challenge required for start charging

## Debugging

A standalone debug script is provided in `scripts/nbpower_debug.py`.
It works without Home Assistant:

```bash
pip install bleak
cd scripts

# Scan for chargers
python3 nbpower_debug.py --scan

# Read all status
python3 nbpower_debug.py --mac F0:C7:7F:01:98:27

# Start charging at 10A for 30 minutes
python3 nbpower_debug.py --mac F0:C7:7F:01:98:27 --start --amps 10 --minutes 30

# Stop charging
python3 nbpower_debug.py --mac F0:C7:7F:01:98:27 --stop

# Send raw command (CMD 0x31, param 0x01 = heartbeat)
python3 nbpower_debug.py --mac F0:C7:7F:01:98:27 --raw 31 01
```

### Logs

To debug the HA integration, add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.nbpower_charger: debug
```

## Known Issues

- Some devices may require pairing before first use. If the integration can't connect,
  try pairing via `bluetoothctl` first.
- The protocol doesn't use CRC, so corrupt BLE packets aren't detected. This is rare in practice.
- Stop charging immediately after start might fail — the device needs a moment to register the start command.

## Contributing

Pull requests welcome! Especially:
- Confirmation of working with other `device_num` values
- Support for DC chargers
- Translation contributions

## Disclaimer

This integration is **not affiliated** with NBPower / Hubei Mairuisi.
It was developed for personal use through reverse engineering of the official app.
Use at your own risk.

The author is not responsible for any damage to your charger, vehicle, or electrical system.

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgements

- Protocol reverse-engineered from NBPowen app v2.0.15
- Built on top of [bleak](https://github.com/hbldh/bleak) for cross-platform BLE
- Inspired by the Home Assistant community
