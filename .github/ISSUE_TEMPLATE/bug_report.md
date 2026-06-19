---
name: Bug report
about: Report a problem with the integration
labels: bug
---

## Environment
- Home Assistant version: 
- Integration version: 
- Charger firmware version (from Diagnostics or app): 
- Charger device_num (from logs): 
- Bluetooth setup: [ ] Built-in [ ] USB dongle [ ] ESPHome BLE proxy

## Problem description

(What happens? What did you expect?)

## Steps to reproduce

1. 
2. 
3. 

## Logs

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.nbpower_charger: debug
```

Paste relevant log lines here:

```

```

## Debug script output

If possible, run `scripts/nbpower_debug.py --mac YOUR_MAC` and paste the output:

```

```
