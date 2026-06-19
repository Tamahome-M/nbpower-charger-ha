"""Config flow for NBPower EV Charger BLE integration."""
from __future__ import annotations

import re
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_MAX_AMPS, CONF_MAX_AMPS

_LOGGER = logging.getLogger(__name__)

MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class NBPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NBPower EV Charger."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_devices: dict[str, str] = {}  # mac → name

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — manual MAC entry."""
        errors: dict[str, str] = {}

        # Try to populate discovered devices via Bluetooth scanner
        if not self._discovered_devices:
            for info in async_discovered_service_info(self.hass, connectable=True):
                name = info.name or ""
                # NBPower devices typically advertise names starting with "NBP"
                if name.upper().startswith("NBP") or "POWER" in name.upper():
                    self._discovered_devices[info.address] = name

        if user_input is not None:
            mac = user_input.get(CONF_MAC, "").strip().upper()
            if not MAC_PATTERN.match(mac):
                errors["base"] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                # Quick connection test
                try:
                    from .nbpower_ble import NBPowerBLEClient
                    client = NBPowerBLEClient(mac)
                    await client.connect(timeout=10.0)
                    info = await client.get_device_info()
                    await client.disconnect()
                    return self.async_create_entry(
                        title=user_input.get(CONF_NAME) or f"NBPower {mac[-8:]}",
                        data={
                            CONF_MAC: mac,
                            CONF_NAME: user_input.get(CONF_NAME) or f"NBPower {mac[-8:]}",
                            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                            CONF_MAX_AMPS: user_input.get(CONF_MAX_AMPS, DEFAULT_MAX_AMPS),
                            "firmware_version": info.firmware_version,
                            "device_num": info.device_num,
                        },
                    )
                except Exception as ex:
                    _LOGGER.error("Cannot connect to %s: %s", mac, ex)
                    errors["base"] = "cannot_connect"

        # Build schema with optional discovered device selector
        if self._discovered_devices:
            device_options = {
                addr: f"{name} ({addr})"
                for addr, name in self._discovered_devices.items()
            }
            schema = vol.Schema({
                vol.Optional("discovered"): vol.In(device_options),
                vol.Optional(CONF_MAC): str,
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=3, max=60)),
                vol.Optional(CONF_MAX_AMPS, default=DEFAULT_MAX_AMPS): vol.All(int, vol.Range(min=6, max=32)),
            })
        else:
            schema = vol.Schema({
                vol.Required(CONF_MAC): str,
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=3, max=60)),
                vol.Optional(CONF_MAX_AMPS, default=DEFAULT_MAX_AMPS): vol.All(int, vol.Range(min=6, max=32)),
            })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "discovered_count": str(len(self._discovered_devices)),
            },
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth auto-discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        name = discovery_info.name or f"NBPower {discovery_info.address[-8:]}"
        self.context["title_placeholders"] = {"name": name}

        self._discovered_devices[discovery_info.address] = name
        return await self.async_step_user()

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return NBPowerOptionsFlow(config_entry)


class NBPowerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for NBPower Charger."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=3, max=60)),
            vol.Optional(
                CONF_MAX_AMPS,
                default=self.config_entry.options.get(CONF_MAX_AMPS, DEFAULT_MAX_AMPS),
            ): vol.All(int, vol.Range(min=6, max=32)),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
