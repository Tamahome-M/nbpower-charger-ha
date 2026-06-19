"""Sensor entities for NBPower EV Charger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_MAC,
    CONF_NAME,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CHARGE_STATE_NAMES
from .coordinator import NBPowerCoordinator


@dataclass
class NBPowerSensorDescription(SensorEntityDescription):
    """Extended sensor description with value extractor."""
    value_fn: Any = None


SENSOR_DESCRIPTIONS: tuple[NBPowerSensorDescription, ...] = (
    # ── Charge state ──────────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="charge_state",
        name="Состояние зарядки",
        icon="mdi:ev-station",
        value_fn=lambda d: CHARGE_STATE_NAMES.get(
            d["status"].charge_state, str(d["status"].charge_state)
        ),
    ),
    NBPowerSensorDescription(
        key="charge_state_code",
        name="Код состояния зарядки",
        icon="mdi:numeric",
        value_fn=lambda d: d["status"].charge_state,
        entity_registry_enabled_default=False,
    ),
    # ── Electricity meter ─────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="voltage",
        name="Напряжение",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda d: d["meter"].voltage,
    ),
    NBPowerSensorDescription(
        key="current",
        name="Ток",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        value_fn=lambda d: d["meter"].current,
    ),
    NBPowerSensorDescription(
        key="power",
        name="Мощность",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda d: d["meter"].power,
    ),
    NBPowerSensorDescription(
        key="active_power",
        name="Активная мощность",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash-outline",
        value_fn=lambda d: d["meter"].active_power,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="energy",
        name="Энергия (сессия)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-charging",
        value_fn=lambda d: d["meter"].energy_kwh,
    ),
    NBPowerSensorDescription(
        key="power_factor",
        name="Коэффициент мощности",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:angle-acute",
        value_fn=lambda d: d["meter"].power_factor,
        entity_registry_enabled_default=False,
    ),
    # ── Temperature ───────────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="temp1",
        name="Температура 1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: (
            None if d["status"].temp1 == 255 else d["status"].temp1
        ),
    ),
    NBPowerSensorDescription(
        key="temp2",
        name="Температура 2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: (
            None if d["status"].temp2 == 255 else d["status"].temp2
        ),
        entity_registry_enabled_default=False,
    ),
    # ── Charging time ─────────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="elapsed_minutes",
        name="Время зарядки",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer",
        value_fn=lambda d: d["timing"].get("elapsed_minutes", 0),
    ),
    NBPowerSensorDescription(
        key="remaining_minutes",
        name="Осталось времени",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_fn=lambda d: d["timing"].get("remaining_minutes", 0),
        entity_registry_enabled_default=False,
    ),
    # ── Requested current ─────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="requested_current",
        name="Запрошенный ток",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        value_fn=lambda d: d["status"].current_amps,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NBPower sensors."""
    coordinator: NBPowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NBPowerSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class NBPowerSensor(CoordinatorEntity[NBPowerCoordinator], SensorEntity):
    """A sensor entity for NBPower charger data."""

    entity_description: NBPowerSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NBPowerCoordinator,
        entry: ConfigEntry,
        description: NBPowerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_MAC]}_{description.key}"
        self._entry = entry

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
    def native_value(self):
        if not self.coordinator.data:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, TypeError, IndexError):
            return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self.coordinator.data)
