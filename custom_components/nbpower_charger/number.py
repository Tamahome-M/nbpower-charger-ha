"""Number entity for NBPower EV Charger — adjustable max charging current."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_MAX_AMPS
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower max current number entity."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NBPowerMaxCurrentNumber(coordinator, entry)])


class NBPowerMaxCurrentNumber(CoordinatorEntity[NBPowerCoordinator], NumberEntity):
    """Slider to set the maximum charging current (6–32 A)."""

    _attr_has_entity_name = True
    _attr_name = "Максимальный ток"
    _attr_icon = "mdi:current-ac"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 6.0
    _attr_native_max_value = 32.0
    _attr_native_step = 1.0

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_MAC]}_max_current"

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
    def native_value(self) -> float:
        return self.coordinator.max_amps

    async def async_set_native_value(self, value: float) -> None:
        """Update max charging current."""
        await self.coordinator.async_set_max_amps(value)
        _LOGGER.info("Max charging current set to %.0f A", value)
        # If currently charging, apply immediately by restarting
        if self.coordinator.is_charging:
            _LOGGER.info("Restarting charge session with new current limit")
            await self.coordinator.async_stop_charging()
            await self.coordinator.async_start_charging(max_amps=value)
