"""NBPower EV Charger BLE integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_MAX_AMPS, CONF_MAX_AMPS, CONF_PASSWORD, DEFAULT_PASSWORD
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.BINARY_SENSOR]


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

    return True


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
