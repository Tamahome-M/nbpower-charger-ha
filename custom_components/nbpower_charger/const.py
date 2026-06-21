"""Constants for NBPower EV Charger integration."""

DOMAIN = "nbpower_charger"

# Config keys
CONF_MAX_AMPS = "max_amps"
CONF_PASSWORD = "password"

# Defaults
DEFAULT_SCAN_INTERVAL = 5   # seconds between polls
DEFAULT_MAX_AMPS = 16       # Amperes
DEFAULT_PASSWORD = "000000" # Default device PIN

# Charge state constants
CHARGE_STATE_UNPLUGGED  = 0
CHARGE_STATE_STANDBY    = 1
CHARGE_STATE_SCHEDULED  = 2
CHARGE_STATE_CHARGING   = 3
CHARGE_STATE_HALF       = 4
CHARGE_STATE_COOLING    = 5
CHARGE_STATE_UPDATING   = 255

CHARGE_STATE_NAMES = {
    CHARGE_STATE_UNPLUGGED:  "Кабель не подключён",
    CHARGE_STATE_STANDBY:    "Ожидание",
    CHARGE_STATE_SCHEDULED:  "По расписанию",
    CHARGE_STATE_CHARGING:   "Зарядка",
    CHARGE_STATE_HALF:       "Пониженная мощность",
    CHARGE_STATE_COOLING:    "Охлаждение",
    CHARGE_STATE_UPDATING:   "Обновление прошивки",
}

# Sensor / entity IDs
SENSOR_CHARGE_STATE     = "charge_state"
SENSOR_VOLTAGE          = "voltage"
SENSOR_CURRENT          = "current"
SENSOR_POWER            = "power"
SENSOR_ENERGY           = "energy"
SENSOR_POWER_FACTOR     = "power_factor"
SENSOR_TEMP1            = "temperature_1"
SENSOR_TEMP2            = "temperature_2"
SENSOR_ELAPSED_TIME     = "elapsed_time"

SWITCH_CHARGING         = "charging"
NUMBER_MAX_AMPS         = "max_current"
