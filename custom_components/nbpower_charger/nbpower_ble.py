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
CMD_HEARTBEAT     = 0x31
CMD_GET_AUTH      = 0x42   # Returns 5-byte challenge for start charge
CMD_START_CHARGE  = 0x43
CMD_SYNC_TIME     = 0x45

# Minimum delay between BLE writes (matches NBPowen app)
WRITE_DELAY_MS = 20


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
                for attempt in range(15):
                    try:
                        response = await self._client.read_gatt_char(self._write_char_uuid)
                        if len(response) >= 2 and response[0] == cmd and response[1] == req_id:
                            _LOGGER.debug("← poll [%02X %02X] %s", cmd, req_id, response[2:].hex())
                            if not future.done():
                                future.set_result(bytes(response[2:]))
                            break
                    except Exception:
                        break
                    await asyncio.sleep(0.05)

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
            return NBPowerStatus()

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
        """CMD 69 — Get charging time (elapsed and remaining minutes)."""
        data = await self._write_command(CMD_SYNC_TIME)
        if not data or len(data) < 4:
            return {"is_charging": False, "elapsed_minutes": 0, "remaining_minutes": 0}

        is_charging = data[0] > 1
        elapsed = (data[1] << 8 | data[2]) if len(data) > 2 else 0
        remaining = (data[6] << 8 | data[7]) if len(data) > 7 else 0

        return {
            "is_charging": is_charging,
            "elapsed_minutes": elapsed,
            "remaining_minutes": remaining,
        }

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
