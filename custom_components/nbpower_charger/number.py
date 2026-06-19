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

from .const import DOMAIN, CONF_MAX_AMPS
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
    """Slider to set the maximum charging current (6–HW_MAX A, step 0.5)."""

    _attr_has_entity_name = True
    _attr_name = "Максимальный ток"
    _attr_icon = "mdi:current-ac"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 6.0
    _attr_native_step = 0.5

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
    def native_max_value(self) -> float:
        """Use the actual hardware limit reported by the charger."""
        return self.coordinator.hw_max_amps

    @property
    def native_value(self) -> float:
        return self.coordinator.max_amps

    async def async_set_native_value(self, value: float) -> None:
        """User changed the slider — save and (if charging) apply immediately."""
        await self.coordinator.async_set_max_amps(value, explicit=True)
        _LOGGER.info("Max charging current set to %.1f A", value)

        # Persist in config entry options so it survives restarts
        new_options = {**self._entry.options, CONF_MAX_AMPS: value}
        self.hass.config_entries.async_update_entry(
            self._entry, options=new_options
        )

        # If currently charging, apply the new limit immediately
        if self.coordinator.is_charging:
            _LOGGER.info("Restarting charge session with new current limit")
            await self.coordinator.async_stop_charging()
            await self.coordinator.async_start_charging(max_amps=value)
        self.async_write_ha_state()
