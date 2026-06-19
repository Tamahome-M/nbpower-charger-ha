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

# Russian labels for stop reason codes
STOP_REASON_LABELS = {
    0:  "Таймер остановки",
    1:  "Ручная остановка",
    2:  "Перегрев",
    3:  "Перегрузка по току",
    4:  "Перенапряжение",
    5:  "Низкое напряжение",
    6:  "Остановка вилки",
    7:  "Полная остановка",
    8:  "Залипание реле",
    9:  "Реле не включается",
    10: "Ненормальная температура вилки",
    11: "Ненормальный счётчик",
    12: "Заземление или НН ненормальное",
    13: "Ненормальное заземление",
    14: "Аварийная кнопка",
    15: "Нет токена",
    16: "Утечка",
    17: "Оффлайн остановка",
    18: "Оффлайн остановка",
}

# Russian labels for WiFi state
WIFI_STATE_LABELS = {
    0: "Выключен",
    1: "Не подключен",
    2: "Подключен, нет интернета",
    3: "Подключен",
}

# Russian labels for cellular network mode
NET_MODE_LABELS = {
    0: "Нет сигнала",
    1: "2G",
    2: "2.5G",
    3: "3G TD",
    4: "4G",
    5: "3G WCDMA",
    15: "Модуль отсутствует",
}


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
    # ── Last session info ─────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="last_session_kwh",
        name="Энергия прошлой сессии",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-charging-high",
        value_fn=lambda d: d["last_session"].session_kwh,
    ),
    NBPowerSensorDescription(
        key="last_session_duration",
        name="Длительность прошлой сессии",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-check",
        value_fn=lambda d: d["last_session"].work_minutes,
    ),
    NBPowerSensorDescription(
        key="last_session_max_temp",
        name="Макс. температура прошлой сессии",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-high",
        value_fn=lambda d: d["last_session"].max_temperature,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="last_session_min_voltage",
        name="Мин. напряжение прошлой сессии",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash-alert",
        value_fn=lambda d: d["last_session"].meter_v_min,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="last_session_requested_amps",
        name="Запрошенный ток прошлой сессии",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        value_fn=lambda d: d["last_session"].requested_amps,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="last_stop_reason",
        name="Причина прошлой остановки",
        icon="mdi:stop-circle-outline",
        value_fn=lambda d: STOP_REASON_LABELS.get(
            d["last_session"].stop_reason_code,
            d["last_session"].stop_reason,
        ),
    ),
    NBPowerSensorDescription(
        key="last_stop_code",
        name="Код прошлой остановки",
        icon="mdi:numeric",
        value_fn=lambda d: d["last_session"].stop_reason_code,
        entity_registry_enabled_default=False,
    ),
    # ── Lifetime totals ───────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="total_kwh",
        name="Всего заряжено",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: d["totals"].total_kwh,
    ),
    NBPowerSensorDescription(
        key="total_charge_count",
        name="Количество сессий",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: d["totals"].total_charge_count,
    ),
    # ── Network / WiFi ────────────────────────────────────────────────────────
    NBPowerSensorDescription(
        key="wifi_state",
        name="WiFi состояние",
        icon="mdi:wifi",
        value_fn=lambda d: WIFI_STATE_LABELS.get(
            d["network"].wifi_state, d["network"].wifi_state_str
        ),
    ),
    NBPowerSensorDescription(
        key="wifi_rssi_level",
        name="WiFi сигнал",
        icon="mdi:wifi-strength-2",
        native_unit_of_measurement="bars",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["network"].wifi_rssi_level,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="network_mode",
        name="Тип сети",
        icon="mdi:signal-cellular-3",
        value_fn=lambda d: NET_MODE_LABELS.get(
            d["network"].net_mode, d["network"].net_mode_str
        ),
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="network_rssi",
        name="Сигнал сети",
        icon="mdi:signal",
        native_unit_of_measurement="bars",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["network"].net_rssi,
        entity_registry_enabled_default=False,
    ),
    NBPowerSensorDescription(
        key="network_operator",
        name="Оператор",
        icon="mdi:sim",
        value_fn=lambda d: d["network"].operator,
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
