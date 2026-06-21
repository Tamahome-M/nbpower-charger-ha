"""Select entity for NBPower EV Charger — run mode (plug-and-charge etc.)."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)

# Mapping between run mode code and Russian display label
RUN_MODE_OPTIONS = {
    "Управление из приложения": 0,
    "Зарядка с вилки (авто)": 1,
    "Запуск ключом": 2,
}
RUN_MODE_LABELS = {v: k for k, v in RUN_MODE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower run mode select."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NBPowerRunModeSelect(coordinator, entry)])


class NBPowerRunModeSelect(CoordinatorEntity[NBPowerCoordinator], SelectEntity):
    """Select the charger run mode."""

    _attr_has_entity_name = True
    _attr_name = "Режим работы"
    _attr_icon = "mdi:cog-transfer"
    _attr_options = list(RUN_MODE_OPTIONS.keys())

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_MAC]}_run_mode"

    @property
    def device_info(self) -> DeviceInfo:
        mac = self._entry.data[CONF_MAC]
        name = self._entry.data.get(CONF_NAME, f"NBPower {mac[-8:]}")
        dev_info = self.coordinator.device_info
        return DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=name,
            manufacturer="NBPower / Hubei Mairuisi",
            model=f"EV Charger (device_num={dev_info.device_num})" if dev_info else "EV Charger",
            sw_version=str(dev_info.firmware_version) if dev_info else None,
            connections={("mac", mac)},
        )

    @property
    def current_option(self) -> str | None:
        return RUN_MODE_LABELS.get(self.coordinator.run_mode)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_select_option(self, option: str) -> None:
        """Change the run mode."""
        run_mode = RUN_MODE_OPTIONS.get(option)
        if run_mode is None:
            _LOGGER.error("Unknown run mode option: %s", option)
            return
        _LOGGER.info("Setting run mode to %s (%d)", option, run_mode)
        success = await self.coordinator.async_set_run_mode(run_mode)
        if not success:
            _LOGGER.warning("Failed to set run mode — check device PIN")
        self.async_write_ha_state()
