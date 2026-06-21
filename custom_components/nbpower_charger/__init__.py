"""NBPower EV Charger BLE integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_MAX_AMPS, CONF_MAX_AMPS, CONF_PASSWORD, DEFAULT_PASSWORD
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.BINARY_SENSOR, Platform.BUTTON]

# ── Service schemas ────────────────────────────────────────────────────────────
SERVICE_CHANGE_PASSWORD = "change_password"
SERVICE_CONFIGURE_WIFI = "configure_wifi"
SERVICE_SET_RUN_MODE = "set_run_mode"

CHANGE_PASSWORD_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("old_password"): cv.string,
    vol.Required("new_password"): cv.string,
})

CONFIGURE_WIFI_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("ssid"): cv.string,
    vol.Required("password"): cv.string,
})

SET_RUN_MODE_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("mode"): vol.In(["0", "1", "2", 0, 1, 2]),
})


def _coordinator_from_device(hass: HomeAssistant, device_id: str) -> NBPowerCoordinator:
    """Resolve a coordinator from a HA device_id."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Device {device_id} not found")
    for entry_id in device.config_entries:
        coord = hass.data.get(DOMAIN, {}).get(entry_id)
        if coord is not None:
            return coord
    raise HomeAssistantError("NBPower coordinator not found for device")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NBPower Charger from a config entry."""
    mac = entry.data[CONF_MAC]
    name = entry.data.get(CONF_NAME, f"NBPower {mac[-8:]}")
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    password = entry.options.get(
        CONF_PASSWORD,
        entry.data.get(CONF_PASSWORD, DEFAULT_PASSWORD),
    )

    coordinator = NBPowerCoordinator(
        hass=hass,
        mac=mac,
        name=name,
        scan_interval=scan_interval,
        password=password,
    )

    # Only apply max_amps as explicit if user has set it via Options.
    # If config_entry has no user-set max_amps, leave coordinator default;
    # async_connect() will seed it from last_session.requested_amps automatically.
    explicit_max_amps = entry.options.get(CONF_MAX_AMPS)
    if explicit_max_amps is not None:
        await coordinator.async_set_max_amps(float(explicit_max_amps), explicit=True)

    try:
        await coordinator.async_connect()
    except Exception as ex:
        _LOGGER.warning("Initial connect failed, will retry: %s", ex)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services once (first config entry)
    _async_register_services(hass)

    return True


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_CHANGE_PASSWORD):
        return

    async def _handle_change_password(call: ServiceCall) -> None:
        coord = _coordinator_from_device(hass, call.data["device_id"])
        ok = await coord.async_change_password(
            call.data["old_password"], call.data["new_password"]
        )
        if not ok:
            raise HomeAssistantError("Не удалось сменить пароль (проверьте старый PIN)")

    async def _handle_configure_wifi(call: ServiceCall) -> None:
        coord = _coordinator_from_device(hass, call.data["device_id"])
        ok = await coord.async_configure_wifi(call.data["ssid"], call.data["password"])
        if not ok:
            raise HomeAssistantError("Не удалось настроить WiFi")

    async def _handle_set_run_mode(call: ServiceCall) -> None:
        coord = _coordinator_from_device(hass, call.data["device_id"])
        mode = int(call.data["mode"])
        ok = await coord.async_set_run_mode(mode)
        if not ok:
            raise HomeAssistantError("Не удалось установить режим (проверьте PIN)")

    hass.services.async_register(
        DOMAIN, SERVICE_CHANGE_PASSWORD, _handle_change_password,
        schema=CHANGE_PASSWORD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CONFIGURE_WIFI, _handle_configure_wifi,
        schema=CONFIGURE_WIFI_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_RUN_MODE, _handle_set_run_mode,
        schema=SET_RUN_MODE_SCHEMA,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Reload the integration only when scan_interval changes
    (max_amps changes are applied live by the number entity).
    """
    coordinator: NBPowerCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    new_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    current_interval = coordinator.update_interval.total_seconds() if coordinator.update_interval else None

    # Sync max_amps from options (e.g. when set via Options flow rather than slider)
    new_max_amps = entry.options.get(CONF_MAX_AMPS)
    if new_max_amps is not None:
        await coordinator.async_set_max_amps(float(new_max_amps), explicit=True)

    # Sync password from options (live, no reload needed)
    new_password = entry.options.get(CONF_PASSWORD)
    if new_password is not None:
        coordinator.set_password(new_password)

    # Only do a full reload when the scan interval changes
    if current_interval != new_interval:
        await hass.config_entries.async_reload(entry.entry_id)
