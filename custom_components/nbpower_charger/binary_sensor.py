"""Binary sensors for NBPower EV Charger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NBPowerCoordinator


@dataclass
class NBPowerBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor description with value extractor."""
    value_fn: Callable[[NBPowerCoordinator], bool] = None


BINARY_SENSORS: tuple[NBPowerBinaryDescription, ...] = (
    NBPowerBinaryDescription(
        key="plug_charge_active",
        name="Зарядка с вилки включена",
        icon="mdi:ev-plug-type2",
        value_fn=lambda c: c.run_mode == 1,
    ),
    NBPowerBinaryDescription(
        key="auto_recharge",
        name="Авто-возобновление",
        icon="mdi:restart",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.charger_config.auto_recharge,
    ),
    NBPowerBinaryDescription(
        key="is_charging",
        name="Идёт зарядка",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        icon="mdi:battery-charging",
        value_fn=lambda c: c.is_charging,
    ),
    NBPowerBinaryDescription(
        key="cable_connected",
        name="Кабель подключён",
        device_class=BinarySensorDeviceClass.PLUG,
        icon="mdi:power-plug",
        value_fn=lambda c: c.charge_state not in (0,),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower binary sensors."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NBPowerBinarySensor(coordinator, entry, desc) for desc in BINARY_SENSORS
    )


class NBPowerBinarySensor(CoordinatorEntity[NBPowerCoordinator], BinarySensorEntity):
    """A binary sensor for NBPower charger state."""

    entity_description: NBPowerBinaryDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
        description: NBPowerBinaryDescription,
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

    @property
    def is_on(self) -> bool:
        try:
            return bool(self.entity_description.value_fn(self.coordinator))
        except (KeyError, TypeError, AttributeError):
            return False

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
