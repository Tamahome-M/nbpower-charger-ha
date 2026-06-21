"""Button entities for NBPower EV Charger — reboot, reset counter."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NBPowerCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class NBPowerButtonDescription(ButtonEntityDescription):
    """Button description with an async press handler."""
    press_fn: Callable[[NBPowerCoordinator], Coroutine[Any, Any, bool]] = None


BUTTONS: tuple[NBPowerButtonDescription, ...] = (
    NBPowerButtonDescription(
        key="reboot",
        name="Перезагрузить",
        icon="mdi:restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_reboot(),
    ),
    NBPowerButtonDescription(
        key="reset_total_energy",
        name="Сбросить общий счётчик",
        icon="mdi:counter",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda c: c.async_reset_total_energy(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower buttons."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NBPowerButton(coordinator, entry, desc) for desc in BUTTONS
    )


class NBPowerButton(CoordinatorEntity[NBPowerCoordinator], ButtonEntity):
    """A button entity for NBPower charger actions."""

    entity_description: NBPowerButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
        description: NBPowerButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_MAC]}_{description.key}"

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

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("Button pressed: %s", self.entity_description.key)
        success = await self.entity_description.press_fn(self.coordinator)
        if not success:
            _LOGGER.warning("Action %s failed (check device PIN)", self.entity_description.key)
