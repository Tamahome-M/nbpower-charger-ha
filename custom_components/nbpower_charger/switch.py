"""Switch entity for NBPower EV Charger — start/stop charging."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CHARGE_STATE_CHARGING, CHARGE_STATE_SCHEDULED
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower charging switch."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NBPowerChargingSwitch(coordinator, entry)])


class NBPowerChargingSwitch(CoordinatorEntity[NBPowerCoordinator], SwitchEntity):
    """Switch to start / stop charging session."""

    _attr_has_entity_name = True
    _attr_name = "Зарядка"
    _attr_icon = "mdi:ev-plug-type2"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_MAC]}_charging"

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
    def is_on(self) -> bool:
        """Return True if charging or scheduled."""
        if not self.coordinator.data:
            return False
        state = self.coordinator.data["status"].charge_state
        return state in (CHARGE_STATE_CHARGING, CHARGE_STATE_SCHEDULED)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict:
        """Extra attributes shown in HA UI."""
        if not self.coordinator.data:
            return {}
        status = self.coordinator.data["status"]
        meter = self.coordinator.data["meter"]
        return {
            "charge_state_code": status.charge_state,
            "requested_amps": status.current_amps,
            "max_amps_configured": self.coordinator.max_amps,
            "session_kwh": meter.energy_kwh,
            "cp_check_valid": status.cp_check_valid,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Start charging."""
        _LOGGER.info("Starting charging on %s", self.coordinator.mac)
        success = await self.coordinator.async_start_charging()
        if not success:
            _LOGGER.warning("Start charging returned failure")

    async def async_turn_off(self, **kwargs) -> None:
        """Stop charging."""
        _LOGGER.info("Stopping charging on %s", self.coordinator.mac)
        await self.coordinator.async_stop_charging()
