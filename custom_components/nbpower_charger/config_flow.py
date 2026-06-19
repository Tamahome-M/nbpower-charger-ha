"""Config flow for NBPower EV Charger BLE integration."""
from __future__ import annotations

import re
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_MAX_AMPS, CONF_MAX_AMPS

_LOGGER = logging.getLogger(__name__)

MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _format_mac(mac: str) -> str:
    """Normalize MAC address to uppercase XX:XX:XX:XX:XX:XX."""
    return mac.strip().upper().replace("-", ":")


def _is_nbpower_name(name: str | None) -> bool:
    """Check if BLE name matches an NBPower charger."""
    n = (name or "").upper()
    return n.startswith("NBP") or "POWER" in n


class NBPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NBPower EV Charger."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_mac: str | None = None
        self._discovered_name: str | None = None
        self._discovered_devices: dict[str, str] = {}

    # ── Auto-discovery via Bluetooth ───────────────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth auto-discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovered_mac = _format_mac(discovery_info.address)
        self._discovered_name = discovery_info.name or f"NBPower {self._discovered_mac[-8:]}"

        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovered device + name + scan interval."""
        if user_input is not None:
            name = user_input.get(CONF_NAME) or self._discovered_name
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            return self.async_create_entry(
                title=name,
                data={
                    CONF_MAC: self._discovered_mac,
                    CONF_NAME: name,
                    CONF_SCAN_INTERVAL: scan_interval,
                },
            )

        schema = vol.Schema({
            vol.Optional(CONF_NAME, default=self._discovered_name): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=DEFAULT_SCAN_INTERVAL,
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
        })

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=schema,
            description_placeholders={
                "name": self._discovered_name,
                "mac": self._discovered_mac,
            },
        )

    # ── Manual / pick from list ────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Entry point from UI: pick from discovered or enter manually."""
        configured_macs = {
            entry.data.get(CONF_MAC, "").upper()
            for entry in self._async_current_entries()
        }
        discovered: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            mac = _format_mac(info.address)
            if mac in configured_macs:
                continue
            if _is_nbpower_name(info.name):
                discovered[mac] = info.name or f"NBPower {mac[-8:]}"

        self._discovered_devices = discovered

        if discovered:
            return await self.async_step_pick_device()
        return await self.async_step_manual()

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick a discovered NBPower charger, or fall back to manual entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input.get(CONF_MAC)
            if mac == "__manual__":
                return await self.async_step_manual()
            if mac:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                self._discovered_mac = mac
                self._discovered_name = self._discovered_devices.get(
                    mac, f"NBPower {mac[-8:]}"
                )
                return await self.async_step_bluetooth_confirm()
            errors["base"] = "no_devices_found"

        options = {
            mac: f"{name} ({mac})"
            for mac, name in self._discovered_devices.items()
        }
        options["__manual__"] = "Ввести MAC вручную"

        schema = vol.Schema({
            vol.Required(CONF_MAC): vol.In(options),
        })
        return self.async_show_form(
            step_id="pick_device",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual MAC address entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac_input = user_input.get(CONF_MAC, "").strip()
            mac = _format_mac(mac_input)

            if not MAC_PATTERN.match(mac):
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME) or f"NBPower {mac[-8:]}"
                scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_MAC: mac,
                        CONF_NAME: name,
                        CONF_SCAN_INTERVAL: scan_interval,
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_MAC): str,
            vol.Optional(CONF_NAME): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=DEFAULT_SCAN_INTERVAL,
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
        })

        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors=errors,
        )

    # ── Options flow ───────────────────────────────────────────────────────────

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return NBPowerOptionsFlow(config_entry)


class NBPowerOptionsFlow(config_entries.OptionsFlow):
    """Options: scan interval and default max current."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_max_amps = self.config_entry.options.get(
            CONF_MAX_AMPS,
            self.config_entry.data.get(CONF_MAX_AMPS, DEFAULT_MAX_AMPS),
        )

        schema = vol.Schema({
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=current_interval,
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
            vol.Optional(
                CONF_MAX_AMPS,
                default=current_max_amps,
            ): vol.All(vol.Coerce(int), vol.Range(min=6, max=32)),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
