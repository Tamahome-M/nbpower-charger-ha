"""NBPower EV Charger BLE protocol client.

Protocol reverse-engineered from NBPowen app v2.0.15 (uni-app JS bundle).

BLE Services (in priority order):
  1. FFE0 service → notify mode
       - FFE1: write + notify (subscribe to notifications)
  2. FFD0 service → POLLING mode (no notify!)
       - FFD1: write + read (write commands here, then read response from same char)

Packet format:
  Send:    [CMD, REQ_ID, param1, param2, ...]
  Receive: [CMD, REQ_ID, data1, data2, ...]
  No checksum.

Write timing: minimum 20ms between writes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

_LOGGER = logging.getLogger(__name__)


class BLECommunicationError(Exception):
    """Raised when the BLE device fails to respond or returns invalid data."""


# ── Charge states (CMD 49, byte 0) ────────────────────────────────────────────
CHARGE_STATES = {
    0: "unplugged",
    1: "standby",
    2: "scheduled",
    3: "charging",
    4: "half_charging",
    5: "cooling",
    255: "updating",
}

# ── Commands ───────────────────────────────────────────────────────────────────
CMD_GET_VERSION   = 0x01
CMD_GET_METER     = 0x08
CMD_GET_NETWORK   = 0x0B
CMD_REBOOT        = 0x10
CMD_GET_TOTALS    = 0x2B   # CMD 43 — total times charged + total kWh
CMD_VERIFY_PWD    = 0x29   # CMD 41 — verify device PIN (BLE: 6 ASCII bytes)
CMD_GET_CONFIG    = 0x2F   # CMD 47 — read full config (run mode, temps, max amps)
CMD_GET_MAXAMP    = 0x2F   # alias (same command)
CMD_SET_CONFIG    = 0x30   # CMD 48 — write full config
CMD_HEARTBEAT     = 0x31
CMD_GET_LAST      = 0x32   # CMD 50 — last charge session info
CMD_GET_AUTH      = 0x42
CMD_START_CHARGE  = 0x43
CMD_SYNC_TIME     = 0x45

# Minimum delay between BLE writes (matches NBPowen app)
WRITE_DELAY_MS = 20


# ── Stop reason codes (CMD 50) ─────────────────────────────────────────────────
STOP_REASONS = {
    0:  "timing_stop",        # Таймер остановки
    1:  "manual_stop",        # Ручная остановка
    2:  "overtemperature",    # Перегрев
    3:  "overcurrent",        # Перегрузка по току
    4:  "overvoltage",        # Перенапряжение
    5:  "low_voltage",        # Низкое напряжение
    6:  "plug_stop",          # Остановка при включении
    7:  "full_stop",          # Полная остановка (зарядка завершена)
    8:  "relay_adhesion",     # Реле прилипание
    9:  "relay_failure",      # Реле не включается
    10: "plug_temp_abnormal", # Ненормальная температура вилки
    11: "meter_abnormal",     # Ненормальный счётчик
    12: "ground_or_nl_error", # Заземление или НН ненормальное
    13: "ground_error",       # Ненормальное заземление
    14: "emergency_button",   # Кнопка аварийного отключения
    15: "no_token",           # Нет токена
    16: "leakage",            # Утечка
    17: "offline_stop",       # Оффлайн остановка
    18: "offline_stop",       # Оффлайн остановка
}

# ── Network mode codes (CMD 11 byte 1, low nibble) ─────────────────────────────
NET_MODE_NAMES = {
    0: "no_signal",
    1: "2g",
    2: "2.5g",
    3: "3g_td",
    4: "4g",
    5: "3g_wcdma",
    15: "no_4g_module",  # 0xF means cellular module absent
}

# ── WiFi state codes (CMD 11 byte 1, bits 4-5) ─────────────────────────────────
WIFI_STATE_NAMES = {
    0: "off",            # WiFi отключен
    1: "disconnected",   # Не подключено к WiFi
    2: "no_network",     # WiFi подключен, но нет сети (Интернета)
    3: "connected",      # Нормальное подключение
}

# ── Run modes (CMD 47/48 byte 4) ───────────────────────────────────────────────
RUN_MODE_NAMES = {
    0: "mobile_control",   # Запуск только из приложения
    1: "plug_start",       # Зарядка автоматически при подключении вилки
    2: "key_switch",       # Запуск физическим ключом/кнопкой
}


@dataclass
class NBPowerStatus:
    """Charger status from CMD 49 heartbeat."""
    charge_state: int = 0
    charge_state_str: str = "unplugged"
    temp1: float = 255.0
    temp2: float = 255.0
    temp3: float = 255.0
    temp4: float = 255.0
    current_amps: float = 0.0
    cp_check_valid: bool = True
    key_state: int = 0


@dataclass
class NBPowerMeterData:
    """Electricity meter data from CMD 8."""
    voltage: float = 0.0
    current: float = 0.0
    power: float = 0.0
    active_power: float = 0.0
    energy_kwh: float = 0.0
    power_factor: float = 0.0


@dataclass
class NBPowerDeviceInfo:
    """Device info from CMD 1."""
    firmware_version: int = 0
    device_num: int = 0
    meter_count: int = 1
    is_dc: bool = False


@dataclass
class NBPowerLastSession:
    """Last charging session info from CMD 50."""
    requested_amps: float = 0.0      # Set ampers (l[12] → pwm → amp)
    max_temperature: float = 0.0     # Max temperature during session (°C)
    timer_minutes: int = 0           # Set timer in minutes (65535 = no limit)
    work_minutes: int = 0            # Actual charging duration in minutes
    stop_reason_code: int = 0        # Numeric stop code
    stop_reason: str = ""            # Human-readable stop reason
    session_kwh: float = 0.0         # kWh consumed in last session
    end_cp_value: int = 0            # CP check value at stop
    meter_v_min: int = 0             # Minimum voltage during session


@dataclass
class NBPowerTotals:
    """Lifetime totals from CMD 43."""
    total_charge_count: int = 0      # Total number of charging sessions
    total_kwh: float = 0.0           # Total energy delivered (kWh)


@dataclass
class NBPowerNetworkInfo:
    """Network / WiFi / Cellular state from CMD 11."""
    # WiFi
    wifi_state: int = 0              # 0=off, 1=not connected, 2=connected no network, 3=connected
    wifi_state_str: str = "off"
    wifi_rssi_level: int = 0         # 0-3 bars
    # Cellular (4G/2G/3G)
    has_4g: bool = False
    net_mode: int = 0                # 0..5
    net_mode_str: str = "no_signal"
    net_rssi: int = 0                # 0-5 bars
    net_sim_present: bool = False
    net_version: int = 0
    operator: str = "-"
    # WAN state (router uplink)
    wan_state: int = 0               # 0-3


@dataclass
class NBPowerChargerConfig:
    """Static charger configuration from CMD 47."""
    max_amps_hw: float = 32.0       # Hardware-supported maximum current (A)
    is_60hz: bool = False           # True = 60Hz mains, False = 50Hz
    run_mode: int = 0               # 0=mobile, 1=plug_start, 2=key_switch
    run_mode_str: str = "mobile_control"
    auto_recharge: bool = False     # Resume charging after power loss
    half_charge_temp: int = 0       # °C threshold to reduce power
    pause_charge_temp: int = 0      # °C threshold to pause
    recovery_charge_temp: int = 0   # °C threshold to resume
    plug_mode_minutes: int = 0      # Duration for plug-start mode
    plug_mode_amps: float = 0.0     # Current for plug-start mode
    raw_config: bytes = b""         # Full raw CMD 47 response for re-saving


class NBPowerBLEClient:
    """Async BLE client for NBPower / NBPowen EV charger.

    Auto-detects the device's BLE service mode:
      - FFE0: notify mode (subscribe and wait for events)
      - FFD0: polling mode (read after each write)
    """

    def __init__(self, mac_address: str) -> None:
        self.mac = mac_address
        self._client: Optional[BleakClient] = None
        self._service_uuid: Optional[str] = None
        self._write_char_uuid: Optional[str] = None
        self._notify_char_uuid: Optional[str] = None
        self._read_char_uuid: Optional[str] = None
        self._use_polling: bool = False
        self._write_no_response: bool = True
        self._req_id: int = 0
        self._pending: dict[tuple[int, int], asyncio.Future] = {}
        self._device_version: int = 0
        self._connected: bool = False
        self._last_write_ms: float = 0.0
        self._lock = asyncio.Lock()  # Serialize BLE writes
        self._password: str = "000000"
        self._pwd_verified_at: float = 0.0  # timestamp of last successful verify
        self._pwd_cache_seconds: float = 9.0  # matches app's 9s cache

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self, timeout: float = 15.0) -> None:
        """Connect to the charger and discover BLE services."""
        self._client = BleakClient(self.mac, timeout=timeout)
        await self._client.connect()
        self._connected = True
        await self._discover_services()
        _LOGGER.info("Connected to NBPower charger %s", self.mac)

    async def disconnect(self) -> None:
        """Disconnect cleanly."""
        self._connected = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected and bool(self._client and self._client.is_connected)

    async def _discover_services(self) -> None:
        """Identify the correct service and characteristics."""
        ffe0_found = False
        ffd0_found = False
        can_write_no_response = False

        for service in self._client.services:
            uuid_upper = service.uuid.upper()

            # FFE0 service → notify mode (preferred if both exist)
            if "FFE0" in uuid_upper and not ffe0_found:
                self._service_uuid = service.uuid
                ffe0_found = True
                self._use_polling = False
                for char in service.characteristics:
                    if "FFE1" in char.uuid.upper():
                        self._write_char_uuid = char.uuid
                        self._notify_char_uuid = char.uuid  # FFE1 supports both
                        if "write-without-response" in char.properties:
                            can_write_no_response = True

            # FFD0 service → polling mode
            elif "FFD0" in uuid_upper and not ffe0_found and not ffd0_found:
                self._service_uuid = service.uuid
                ffd0_found = True
                self._use_polling = True
                for char in service.characteristics:
                    cu = char.uuid.upper()
                    if "FFD1" in cu:
                        self._write_char_uuid = char.uuid
                        if "write-without-response" in char.properties:
                            can_write_no_response = True
                    elif "FFD2" in cu:
                        self._notify_char_uuid = char.uuid
                    elif "FFD3" in cu:
                        self._read_char_uuid = char.uuid

        if not self._write_char_uuid:
            raise RuntimeError("NBPower characteristic (FFE1/FFD1) not found")

        # Match app logic: writeType = "writeNoResponse" if (noNotify || canWriteNoRsp)
        self._write_no_response = self._use_polling or can_write_no_response

        _LOGGER.debug(
            "NBPower service detected: %s, write=%s, notify=%s, polling=%s, no_response=%s",
            self._service_uuid, self._write_char_uuid, self._notify_char_uuid,
            self._use_polling, self._write_no_response,
        )

        # Subscribe to notify only for FFE0 service
        if not self._use_polling and self._notify_char_uuid:
            try:
                await self._client.start_notify(self._notify_char_uuid, self._on_notification)
                _LOGGER.debug("Subscribed to notify on %s", self._notify_char_uuid)
            except Exception as e:
                _LOGGER.warning("Notify subscription failed, falling back to polling: %s", e)
                self._use_polling = True

    def _get_req_id(self) -> int:
        self._req_id = (self._req_id + 1) % 256
        return self._req_id

    def _on_notification(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle incoming notification (notify mode only)."""
        if len(data) < 2:
            return
        key = (data[0], data[1])
        fut = self._pending.get(key)
        if fut and not fut.done():
            fut.set_result(bytes(data[2:]))

    async def _write_command(self, cmd: int, params: list[int] = None,
                              timeout: float = 5.0) -> bytes:
        """Send a command and wait for response.

        Polling mode: write to FFD1, then read same characteristic.
        Notify mode: write to FFE1, response arrives via notification.
        """
        if params is None:
            params = []

        async with self._lock:
            req_id = self._get_req_id()
            packet = bytes([cmd, req_id] + params)
            key = (cmd, req_id)

            # Enforce 20ms minimum between writes
            now_ms = time.time() * 1000
            elapsed = now_ms - self._last_write_ms
            if elapsed < WRITE_DELAY_MS:
                await asyncio.sleep((WRITE_DELAY_MS - elapsed) / 1000)
            self._last_write_ms = time.time() * 1000

            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            self._pending[key] = future

            _LOGGER.debug("→ %s [%02X %02X] %s",
                          "writeNoResp" if self._write_no_response else "write",
                          cmd, req_id, bytes(params).hex())

            try:
                await self._client.write_gatt_char(
                    self._write_char_uuid,
                    packet,
                    response=not self._write_no_response,
                )
            except Exception as ex:
                self._pending.pop(key, None)
                _LOGGER.error("BLE write failed: %s", ex)
                return b""

            # In polling mode, read response from the write characteristic
            if self._use_polling:
                await asyncio.sleep(0.02)
                got_any = False
                for attempt in range(15):
                    try:
                        response = await self._client.read_gatt_char(self._write_char_uuid)
                        if len(response) >= 2:
                            got_any = True
                            if response[0] == cmd and response[1] == req_id:
                                _LOGGER.debug("← poll [%02X %02X] %s",
                                              cmd, req_id, response[2:].hex())
                                if not future.done():
                                    future.set_result(bytes(response[2:]))
                                break
                            else:
                                # Stale data: a different command's response
                                _LOGGER.debug("← poll stale [%02X %02X] (waiting for %02X %02X), retry",
                                              response[0], response[1], cmd, req_id)
                    except Exception as ex:
                        _LOGGER.debug("polling read attempt %d failed: %s", attempt, ex)
                        break
                    await asyncio.sleep(0.05)
                if not got_any:
                    _LOGGER.debug("polling: no data read at all for CMD 0x%02X", cmd)

            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout on CMD 0x%02X req %d", cmd, req_id)
                return b""
            finally:
                self._pending.pop(key, None)

    # ── High-level API ─────────────────────────────────────────────────────────

    async def get_device_info(self) -> NBPowerDeviceInfo:
        """CMD 1 — Get firmware version and device model."""
        data = await self._write_command(CMD_GET_VERSION)
        if not data:
            return NBPowerDeviceInfo()
        info = NBPowerDeviceInfo(
            firmware_version=data[0] if len(data) > 0 and data[0] != 255 else 0,
            device_num=data[1] if len(data) > 1 and data[1] != 255 else 0,
            meter_count=data[2] if len(data) > 2 else 1,
            is_dc=(data[1] == 30 if len(data) > 1 else False),
        )
        self._device_version = info.firmware_version
        _LOGGER.debug("Device info: %s", info)
        return info

    async def get_status(self) -> NBPowerStatus:
        """CMD 49 — Heartbeat: charge state, temperatures, current."""
        data = await self._write_command(CMD_HEARTBEAT, [0x01])
        if not data or len(data) < 4:
            raise BLECommunicationError("Heartbeat response too short or empty")

        def parse_temp(raw: int) -> float:
            return 255.0 if raw == 255 else float(raw - 40)

        charge_state = data[0]
        pwm_range = data[3]
        current_amps = self._pwm_to_amp(pwm_range)

        return NBPowerStatus(
            charge_state=charge_state,
            charge_state_str=CHARGE_STATES.get(charge_state, f"unknown_{charge_state}"),
            temp1=parse_temp(data[1]),
            temp3=parse_temp(data[2]),
            temp2=parse_temp(data[4]) if len(data) > 4 else 255.0,
            temp4=parse_temp(data[15]) if len(data) > 15 else 255.0,
            current_amps=current_amps,
            cp_check_valid=(data[8] == 1) if len(data) > 8 else True,
            key_state=data[10] if len(data) > 10 else 0,
        )

    async def get_meter_data(self) -> NBPowerMeterData:
        """CMD 8 — Get voltage, current, power, energy."""
        data = await self._write_command(CMD_GET_METER)
        if not data or len(data) < 8:
            return NBPowerMeterData()

        ver = self._device_version

        if ver > 27:
            voltage = (data[0] << 8 | data[1]) / 10
            current = (data[2] << 8 | data[3]) / 10
            power = voltage * current
            active_power = float(data[4] << 8 | data[5])
            energy_kwh = (data[6] << 8 | data[7]) / 100
        else:
            voltage = (data[1] << 8 | data[2]) / 10
            current = (data[3] << 8 | data[4]) / 10
            power = voltage * current
            p_reg = data[5] << 16 | data[6] << 8 | data[7]
            divisor = 1 if ver > 17 else 10
            active_power = (data[8] << 8 | data[9]) / divisor if len(data) > 9 else 0.0
            g = (data[10] << 8 | data[11]) if len(data) > 11 else 0
            m = (data[12] << 8 | data[13]) if len(data) > 13 else 0
            if p_reg > 0:
                each_kwh_pf = 3_600_000_000_000 / (1.88 * p_reg * 2)
                energy_kwh = (65536 * g + m) / each_kwh_pf if each_kwh_pf > 0 else 0.0
            else:
                energy_kwh = 0.0

        pf = (active_power / power * 100) if power > 0 else 0.0

        return NBPowerMeterData(
            voltage=round(voltage, 1),
            current=round(current, 1),
            power=round(power, 1),
            active_power=round(active_power, 0),
            energy_kwh=round(energy_kwh, 3),
            power_factor=round(pf, 1),
        )

    async def _get_auth_challenge(self) -> Optional[bytes]:
        """CMD 66 — Get 5-byte challenge for charge start authorization."""
        data = await self._write_command(CMD_GET_AUTH)
        if data and len(data) >= 5:
            return bytes(data[:5])
        return None

    @staticmethod
    def _compute_start_token(challenge: bytes, minutes_hi: int, minutes_lo: int) -> list[int]:
        """Compute the 6-byte token from auth challenge + duration.

        Reproduces the exact formula from the NBPowen app:
            l[0] = (f[0]<<8|f[1]) % (255 & (t+1|e)) & 255
            l[1] = (f[1]<<8|f[2]) % (255 & (t+2|e)) & 255
            l[2] = (f[2]<<8|f[3]) % (255 & (t+3|e)) & 255
            l[3] = (f[3]<<8|f[4]) % (255 & (t+4|e)) & 255
            l[4] = (f[4]<<8|t|e) % 34 & 255
            l[5] = (l[0]+l[1]+l[2]+l[3]+l[4]) % 35 & 255
        """
        f = challenge
        t = minutes_hi
        e = minutes_lo
        token = [0] * 6

        def safe_mod(a, b):
            return a % b if b != 0 else 0

        token[0] = safe_mod((f[0] << 8 | f[1]), 255 & (t + 1 | e)) & 0xFF
        token[1] = safe_mod((f[1] << 8 | f[2]), 255 & (t + 2 | e)) & 0xFF
        token[2] = safe_mod((f[2] << 8 | f[3]), 255 & (t + 3 | e)) & 0xFF
        token[3] = safe_mod((f[3] << 8 | f[4]), 255 & (t + 4 | e)) & 0xFF
        token[4] = ((f[4] << 8 | t | e) % 34) & 0xFF
        token[5] = (sum(token[:5]) % 35) & 0xFF
        return token

    def set_password(self, password: str) -> None:
        """Set the device PIN used for protected commands (start/stop charge)."""
        self._password = (password or "000000")[:6]
        self._pwd_verified_at = 0.0  # force re-verification

    async def verify_password(self, password: str | None = None) -> bool:
        """CMD 41 — Verify device PIN.

        BLE format: write [6 ASCII bytes] of the PIN, padded with '0' to 6 chars.
        Response byte[0]: 1 = OK, 2 = locked (5 wrong tries), 0/other = wrong.

        Returns True if accepted.
        """
        pwd = (password if password is not None else self._password)
        pwd_padded = (pwd[:6] + "000000")[:6]
        pwd_bytes = [ord(c) for c in pwd_padded]

        data = await self._write_command(CMD_VERIFY_PWD, pwd_bytes)
        if not data:
            _LOGGER.warning("Password verify: no response")
            return False

        result = data[0]
        if result in (1, 255):
            self._pwd_verified_at = time.time()
            _LOGGER.debug("Password accepted")
            return True
        if result == 2:
            _LOGGER.error("Password locked: too many wrong attempts (5)")
            return False
        _LOGGER.warning("Password rejected (byte[0]=%d)", result)
        return False

    async def _ensure_password(self) -> bool:
        """Verify password if cache expired. Returns True if authorized."""
        now = time.time()
        if now - self._pwd_verified_at < self._pwd_cache_seconds:
            return True  # still cached
        return await self.verify_password()

    async def start_charging(self, max_amps: float = 16.0,
                              minutes: int = 65535,
                              delay_minutes: int = 0) -> bool:
        """Start charging.

        Args:
            max_amps: Maximum charging current (6–32 A).
            minutes: Duration in minutes. Default 65535 = unlimited (matches app).
            delay_minutes: Delay before starting.

        Returns:
            True on success.
        """
        max_amps = max(6.0, min(32.0, max_amps))
        pwm = max(13, round(250 * max_amps / 60))
        minutes_hi = (minutes >> 8) & 0xFF
        minutes_lo = minutes & 0xFF

        # Verify device PIN first (CMD 41), as the app does before CMD 67
        if not await self._ensure_password():
            _LOGGER.error("Cannot start charging: password verification failed")
            return False

        # Get auth challenge and compute real token
        challenge = await self._get_auth_challenge()
        if challenge is None:
            _LOGGER.error("Cannot start charging: failed to get auth challenge")
            return False

        token = self._compute_start_token(challenge, minutes_hi, minutes_lo)

        params = token + [
            minutes_hi, minutes_lo,
            (delay_minutes >> 8) & 0xFF, delay_minutes & 0xFF,
            pwm,
            0, 0,  # DC voltage (AC = 0)
        ]

        data = await self._write_command(CMD_START_CHARGE, params)
        if not data:
            return False

        result = data[0]
        success = not (result < 2 and minutes != 0)
        _LOGGER.info("Start charge result=%d success=%s", result, success)
        return success

    async def stop_charging(self) -> bool:
        """Stop the current charging session.

        Same CMD 67 as start, but with minutes=0 and hardcoded token.
        Replicates startCharge(0) behavior from the app.
        """
        # Verify device PIN first (CMD 41), as the app does before CMD 67
        if not await self._ensure_password():
            _LOGGER.error("Cannot stop charging: password verification failed")
            return False

        # Per app logic: when called with the 'recharge' flag, hardcoded token is used.
        # For stop (minutes=0), the simple token [1,1,1,1,1,0] works.
        params = [1, 1, 1, 1, 1, 0,    # hardcoded token
                  0, 0,                  # minutes = 0
                  0, 0,                  # delay = 0
                  0, 0, 0]               # pwm = 0, DC voltage = 0
        data = await self._write_command(CMD_START_CHARGE, params)
        _LOGGER.info("Stop charge sent, response: %s", data.hex() if data else "none")
        return bool(data)

    async def get_charging_time(self) -> dict:
        """CMD 69 — Get charging time.

        Response layout (per app's syncChargingTime function):
            data[0]    = charge state (>1 = charging)
            data[1..2] = configured timer in minutes (65535 = unlimited)
            data[3..4] = elapsed minutes since charge start
            data[6..7] = remaining (countdown) minutes
        """
        data = await self._write_command(CMD_SYNC_TIME)
        if not data or len(data) < 5:
            return {
                "is_charging": False,
                "elapsed_minutes": 0,
                "remaining_minutes": 0,
                "configured_minutes": 0,
            }

        is_charging = data[0] > 1
        configured = (data[1] << 8 | data[2]) if len(data) > 2 else 0
        elapsed = (data[3] << 8 | data[4]) if len(data) > 4 else 0
        remaining = (data[6] << 8 | data[7]) if len(data) > 7 else 0

        # 65535 = unlimited / no timer
        if configured == 0xFFFF:
            configured = 0

        return {
            "is_charging": is_charging,
            "elapsed_minutes": elapsed,
            "remaining_minutes": remaining,
            "configured_minutes": configured,
        }

    async def get_charger_config(self) -> NBPowerChargerConfig:
        """CMD 47 — Get full charger configuration.

        Note: this is a protected command — the device requires a valid PIN
        (verified via CMD 41) before it returns the config.

        Response layout (15 bytes, per app's showConfigSetting):
            n[0]  = flags: bit0=cpCheck, bit1=keyCheck, bit2=digitalProtocol,
                    bit3=autoRecharge, bit4=cpRangeType, bit5=aclCheck,
                    bit6=switchCheck, bit7=50/60Hz
            n[1]  = half charge temp threshold (°C)
            n[2]  = pause charge temp threshold (°C)
            n[3]  = recovery charge temp threshold (°C)
            n[4]  = run mode (0=mobile, 1=plug_start, 2=key_switch)
            n[5..6] = plug-mode run minutes
            n[7]  = plug-mode pwm range
            n[10] = max amps (hardware, capped at 50)
        """
        # CMD 47 is protected — verify PIN first
        if not await self._ensure_password():
            _LOGGER.debug("get_charger_config: password not verified, returning defaults")
            return NBPowerChargerConfig()

        data = await self._write_command(CMD_GET_CONFIG)
        if not data or len(data) < 11:
            return NBPowerChargerConfig()

        n = data
        max_amps = float(min(n[10] or 32, 50))
        is_60hz = bool((n[0] >> 7) & 1)
        auto_recharge = bool((n[0] >> 3) & 1)
        run_mode = n[4] if len(n) > 4 else 0
        plug_minutes = (n[5] << 8 | n[6]) if len(n) > 6 else 0
        plug_amps = self._pwm_to_amp(n[7]) if len(n) > 7 else 0.0

        return NBPowerChargerConfig(
            max_amps_hw=max_amps,
            is_60hz=is_60hz,
            run_mode=run_mode,
            run_mode_str=RUN_MODE_NAMES.get(run_mode, f"unknown_{run_mode}"),
            auto_recharge=auto_recharge,
            half_charge_temp=n[1] if len(n) > 1 else 0,
            pause_charge_temp=n[2] if len(n) > 2 else 0,
            recovery_charge_temp=n[3] if len(n) > 3 else 0,
            plug_mode_minutes=plug_minutes,
            plug_mode_amps=plug_amps,
            raw_config=bytes(n),
        )

    async def set_run_mode(self, run_mode: int) -> bool:
        """CMD 48 — Set the charger run mode.

        Args:
            run_mode: 0=mobile control, 1=plug start (auto-charge on plug),
                      2=key switch.

        This reads the current config (CMD 47), changes only byte 4 (run mode),
        and writes the whole config back (CMD 48), preserving all other settings.
        Requires the device PIN.
        """
        if run_mode not in (0, 1, 2):
            _LOGGER.error("Invalid run mode: %s", run_mode)
            return False

        # Verify PIN (CMD 48 is a protected command)
        if not await self._ensure_password():
            _LOGGER.error("Cannot set run mode: password verification failed")
            return False

        # Read current config fresh to get all current bytes
        cfg = await self.get_charger_config()
        if not cfg.raw_config or len(cfg.raw_config) < 11:
            _LOGGER.error("Cannot set run mode: failed to read current config")
            return False

        # Build the config payload from raw, changing only byte 4 (run mode)
        config = bytearray(cfg.raw_config)
        config[4] = run_mode

        # For plug_start mode, ensure valid minutes and amps are set
        if run_mode == 1:
            plug_minutes = (config[5] << 8 | config[6]) if len(config) > 6 else 0
            if plug_minutes < 1:
                plug_minutes = 600  # default 10 hours
                config[5] = (plug_minutes >> 8) & 0xFF
                config[6] = plug_minutes & 0xFF
            if len(config) > 7 and config[7] < 25:  # pwm < 6A
                config[7] = self._amp_to_pwm(6.0)

        data = await self._write_command(CMD_SET_CONFIG, list(config))
        if not data:
            return False
        success = data[0] == 1
        _LOGGER.info("Set run mode to %d: %s", run_mode, "OK" if success else "FAILED")
        return success

    async def get_last_session(self) -> NBPowerLastSession:
        """CMD 50 — Get information about the last charging session.

        Response layout (per app):
            n[0]    = min voltage during session (if meter supported)
            n[2..3] = work_minutes (big-endian)  — actual charging time
            n[4..5] = u (used for kWh calculation, version > 27: kwh*100)
            n[6..7] = end_cp_value
            n[8]    = max temperature + 40 (raw)
            n[9..10] = timer_minutes set
            n[11]   = stop reason packed:
                - DC: full byte = stop reason code
                - AC (fw <= 29): high nibble = pre-fault state, low nibble = stop code
                - AC (fw > 29): bits 7..3 = pre-fault state, bits 4..0 = stop code
            n[12]   = pwm range (set current → amp via pwm_to_amp)
        """
        data = await self._write_command(CMD_GET_LAST)
        if not data or len(data) < 12:
            return NBPowerLastSession()

        n = data
        ver = self._device_version
        meter_v_min = n[0] if len(n) > 0 else 0
        work_minutes = (n[2] << 8 | n[3]) if len(n) > 3 else 0
        u = (n[4] << 8 | n[5]) if len(n) > 5 else 0
        end_cp = (n[6] << 8 | n[7]) if len(n) > 7 else 0
        max_temp = (n[8] - 40) if len(n) > 8 else 0
        timer_minutes = (n[9] << 8 | n[10]) if len(n) > 10 else 0

        # Decode stop reason
        stop_code = 0
        if len(n) > 11:
            raw = n[11]
            if ver > 29:
                stop_code = raw & 0x1F        # bits 0-4
            else:
                stop_code = raw & 0x0F        # bits 0-3
        stop_reason = STOP_REASONS.get(stop_code, f"unknown_{stop_code}")

        # Decode set ampers
        requested_amps = 0.0
        if len(n) > 12:
            requested_amps = self._pwm_to_amp(n[12])

        # kWh calculation (works for fw > 27, simpler case)
        session_kwh = round(u / 100, 2) if ver > 27 else 0.0

        return NBPowerLastSession(
            requested_amps=requested_amps,
            max_temperature=float(max_temp),
            timer_minutes=timer_minutes,
            work_minutes=work_minutes,
            stop_reason_code=stop_code,
            stop_reason=stop_reason,
            session_kwh=session_kwh,
            end_cp_value=end_cp,
            meter_v_min=meter_v_min,
        )

    async def get_network_info(self) -> NBPowerNetworkInfo:
        """CMD 11 — Get WiFi / cellular network state.

        Per the app's bit-packing in CMD 11 response [0]:
            h[0] = response length flag
            h[1] = net_mode (bits 0-3) | wifi_state (bits 4-5) | wifi_rssi (bits 6-7)
            h[2] = net_rssi (bits 0-5, scaled 0-31) | wan_state (bits 6-7)
            h[3] = sim_present (bit 0) | net_version (bits 1-7)
            h[4] = operator code (lookup in operatorsNums table)
        """
        data = await self._write_command(CMD_GET_NETWORK, [0x00])
        if not data or len(data) < 5:
            return NBPowerNetworkInfo()

        h = data
        net_mode = h[1] & 0x0F
        wifi_state = (h[1] >> 4) & 0x03
        wifi_rssi = (h[1] >> 6) & 0x03
        net_rssi_raw = h[2] & 0x3F
        net_rssi = round(5 * net_rssi_raw / 31) if net_rssi_raw else 0
        wan_state = (h[2] >> 6) & 0x03
        sim_present = bool(h[3] & 0x01)
        net_version = h[3] >> 1
        op_code = h[4]

        # Operator: app maps op_code → name, but all entries are "LTE" in firmware data
        operator = "LTE" if op_code else "-"

        return NBPowerNetworkInfo(
            wifi_state=wifi_state,
            wifi_state_str=WIFI_STATE_NAMES.get(wifi_state, f"unknown_{wifi_state}"),
            wifi_rssi_level=wifi_rssi,
            has_4g=(net_mode != 15),
            net_mode=net_mode,
            net_mode_str=NET_MODE_NAMES.get(net_mode, f"unknown_{net_mode}"),
            net_rssi=net_rssi,
            net_sim_present=sim_present,
            net_version=net_version,
            operator=operator,
            wan_state=wan_state,
        )

    async def get_totals(self) -> NBPowerTotals:
        """CMD 43 — Get lifetime totals: number of sessions and total kWh.

        Response layout (fw > 27):
            p[0..1] = total charge count
            p[2..5] = total kWh × 100 (big-endian, 32-bit)
        """
        data = await self._write_command(CMD_GET_TOTALS)
        if not data or len(data) < 6:
            return NBPowerTotals()

        p = data
        ver = self._device_version
        total_count = p[0] << 8 | p[1]

        if ver > 27:
            # Big endian 32-bit value
            total_kwh_raw = (p[2] << 24) | (p[3] << 16) | (p[4] << 8) | p[5]
            total_kwh = round(total_kwh_raw / 100, 2)
        else:
            # Older firmware: high word and low word swapped
            high = p[2] << 8 | p[3] if len(p) > 3 else 0
            low = p[4] << 8 | p[5] if len(p) > 5 else 0
            total_kwh = round((high * 65536 + low) / 100, 2)

        return NBPowerTotals(
            total_charge_count=total_count,
            total_kwh=total_kwh,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _amp_to_pwm(amps: float) -> int:
        return round(250 * amps / 60)

    @staticmethod
    def _pwm_to_amp(pwm: int) -> float:
        raw = pwm / 250 * 60
        frac = raw % 1
        if 0.3 <= frac <= 0.7:
            frac = 0.5
        elif frac > 0.7:
            frac = 1.0
        else:
            frac = 0.0
        return int(raw) + frac

    @staticmethod
    async def discover(timeout: float = 10.0) -> list[dict]:
        """Scan for NBPower chargers nearby."""
        found = []
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for address, (device, adv) in discovered.items():
            name = device.name or getattr(adv, "local_name", None) or ""
            if "nbp" in name.lower() or "power" in name.lower():
                found.append({
                    "name": name,
                    "address": address,
                    "rssi": getattr(adv, "rssi", None),
                })
        return found
