"""DataUpdateCoordinator for NBPower EV Charger."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

try:
    from homeassistant.components.bluetooth import async_last_service_info
except ImportError:  # pragma: no cover
    async_last_service_info = None

from .nbpower_ble import (
    NBPowerBLEClient,
    NBPowerStatus,
    NBPowerMeterData,
    NBPowerDeviceInfo,
    NBPowerLastSession,
    NBPowerTotals,
    NBPowerNetworkInfo,
    NBPowerChargerConfig,
)
from .const import DOMAIN, DEFAULT_MAX_AMPS

_LOGGER = logging.getLogger(__name__)

# Slow-changing data (last session, totals) — poll every N regular cycles
SLOW_POLL_MULTIPLIER = 6  # at 5s interval → ~30s for slow data


class NBPowerCoordinator(DataUpdateCoordinator):
    """Manages polling the NBPower charger and holds shared state."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: str,
        name: str,
        scan_interval: int,
        password: str = "000000",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"NBPower {name}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.mac = mac
        self.charger_name = name
        self.client = NBPowerBLEClient(mac)
        self.client.set_password(password)
        self.device_info: NBPowerDeviceInfo | None = None
        self.charger_config: NBPowerChargerConfig = NBPowerChargerConfig()
        self._max_amps: float = DEFAULT_MAX_AMPS
        self._max_amps_explicitly_set: bool = False
        self._reconnect_lock = asyncio.Lock()
        self._poll_counter: int = 0
        # Cache slow-changing data between slow polls
        self._cached_last_session: NBPowerLastSession = NBPowerLastSession()
        self._cached_totals: NBPowerTotals = NBPowerTotals()
        self._cached_network: NBPowerNetworkInfo = NBPowerNetworkInfo()
        # Lifetime energy accumulator for the HA Energy Dashboard.
        # The device's session kWh (CMD 8) grows live but resets to 0 each session;
        # the device's total kWh (CMD 43) only updates at session end. We build our
        # own monotonically-increasing total by summing session deltas, which is
        # exactly what the Energy Dashboard needs.
        self._energy_total_kwh: float = 0.0
        self._last_session_kwh: float = 0.0
        self._energy_restored: bool = False

    # ── Connection management ──────────────────────────────────────────────────

    async def async_connect(self) -> None:
        await self.client.connect(timeout=15.0)
        self.device_info = await self.client.get_device_info()
        # Read static configuration (hardware max amps + frequency)
        try:
            self.charger_config = await self.client.get_charger_config()
            _LOGGER.info(
                "Charger config: hw_max_amps=%s, %s Hz",
                self.charger_config.max_amps_hw,
                "60" if self.charger_config.is_60hz else "50",
            )
        except Exception as ex:
            _LOGGER.warning("Failed to read charger config (CMD 47): %s", ex)
        # Read last session to seed max_amps from real-world usage
        try:
            last = await self.client.get_last_session()
            self._cached_last_session = last
            if not self._max_amps_explicitly_set and last.requested_amps > 0:
                self._max_amps = last.requested_amps
                _LOGGER.info(
                    "Initial max_amps seeded from last session: %.1f A",
                    self._max_amps,
                )
        except Exception as ex:
            _LOGGER.debug("Failed to read last session: %s", ex)

        _LOGGER.info(
            "NBPower charger connected: %s (fw=%d, device_num=%d)",
            self.mac,
            self.device_info.firmware_version,
            self.device_info.device_num,
        )

    async def async_disconnect(self) -> None:
        await self.client.disconnect()

    async def _ensure_connected(self) -> bool:
        if self.client.is_connected:
            return True
        async with self._reconnect_lock:
            if self.client.is_connected:
                return True
            try:
                _LOGGER.debug("Reconnecting to %s...", self.mac)
                await self.client.connect(timeout=10.0)
                if self.device_info is None:
                    self.device_info = await self.client.get_device_info()
                return True
            except Exception as ex:
                _LOGGER.warning("Reconnect failed: %s", ex)
                return False

    # ── Data polling ───────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        if not await self._ensure_connected():
            raise UpdateFailed("Bluetooth connection unavailable")

        try:
            # Always poll fast-changing data
            status: NBPowerStatus = await self.client.get_status()
            meter: NBPowerMeterData = await self.client.get_meter_data()
            timing: dict = await self.client.get_charging_time()

            _LOGGER.debug(
                "Status: charge_state=%d (%s), volt=%.1f, amp=%.2f, kwh=%.3f",
                status.charge_state, status.charge_state_str,
                meter.voltage, meter.current, meter.energy_kwh,
            )

            # ── Lifetime energy accumulator (for Energy Dashboard) ──────────────
            # The session counter (meter.energy_kwh) grows while charging and
            # resets to 0 at the start of a new session. We track the delta and
            # add it to a monotonic lifetime total.
            session_kwh = meter.energy_kwh
            if session_kwh >= self._last_session_kwh:
                # Normal growth within the same session
                delta = session_kwh - self._last_session_kwh
            else:
                # Counter reset (new session) — the new value is this session's accrual
                delta = session_kwh
            # Guard against spurious huge jumps (bad BLE read)
            if 0 <= delta < 5:
                self._energy_total_kwh += delta
            self._last_session_kwh = session_kwh

            # Slow data: last session + totals + network every Nth cycle
            self._poll_counter += 1
            if self._poll_counter % SLOW_POLL_MULTIPLIER == 1:
                try:
                    self._cached_last_session = await self.client.get_last_session()
                except Exception as ex:
                    _LOGGER.debug("get_last_session failed: %s", ex)
                try:
                    self._cached_totals = await self.client.get_totals()
                except Exception as ex:
                    _LOGGER.debug("get_totals failed: %s", ex)
                try:
                    self._cached_network = await self.client.get_network_info()
                except Exception as ex:
                    _LOGGER.debug("get_network_info failed: %s", ex)
                try:
                    self.charger_config = await self.client.get_charger_config()
                except Exception as ex:
                    _LOGGER.debug("get_charger_config refresh failed: %s", ex)

            return {
                "status": status,
                "meter": meter,
                "timing": timing,
                "last_session": self._cached_last_session,
                "totals": self._cached_totals,
                "network": self._cached_network,
                "energy_lifetime_kwh": round(self._energy_total_kwh, 3),
                "available": True,
            }
        except Exception as ex:
            _LOGGER.warning("Poll error: %s — keeping previous data", ex)
            self.client._connected = False
            # HA's DataUpdateCoordinator preserves self.data when UpdateFailed is raised,
            # so entities will show last good values until next successful poll.
            raise UpdateFailed(f"Error communicating with charger: {ex}") from ex

    # ── Control actions ────────────────────────────────────────────────────────

    async def async_start_charging(self, max_amps: float | None = None) -> bool:
        if not await self._ensure_connected():
            _LOGGER.error("Cannot start charging: not connected")
            return False
        amps = max_amps if max_amps is not None else self._max_amps
        result = await self.client.start_charging(max_amps=amps)
        if result:
            await self.async_request_refresh()
        return result

    async def async_stop_charging(self) -> bool:
        if not await self._ensure_connected():
            _LOGGER.error("Cannot stop charging: not connected")
            return False
        result = await self.client.stop_charging()
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_max_amps(self, amps: float, *, explicit: bool = True) -> None:
        """Set the max charging current (next session).

        Args:
            amps: Target current in Amperes.
            explicit: True when set by user/UI; False for internal seeding from device.
        """
        hw_max = self.charger_config.max_amps_hw or 32.0
        self._max_amps = max(6.0, min(hw_max, float(amps)))
        if explicit:
            self._max_amps_explicitly_set = True

    def set_password(self, password: str) -> None:
        """Update the device PIN used for protected commands."""
        self.client.set_password(password)

    async def async_set_run_mode(self, run_mode: int) -> bool:
        """Change the charger run mode (0=mobile, 1=plug-start, 2=key)."""
        if not await self._ensure_connected():
            _LOGGER.error("Cannot set run mode: not connected")
            return False
        result = await self.client.set_run_mode(run_mode)
        if result:
            # Re-read config so the new mode is reflected
            try:
                self.charger_config = await self.client.get_charger_config()
            except Exception as ex:
                _LOGGER.debug("Failed to re-read config after run mode change: %s", ex)
            await self.async_request_refresh()
        return result

    async def async_change_password(self, old_pwd: str, new_pwd: str) -> bool:
        """Change the device PIN."""
        if not await self._ensure_connected():
            return False
        return await self.client.change_password(old_pwd, new_pwd)

    async def async_reboot(self) -> bool:
        """Reboot the charger."""
        if not await self._ensure_connected():
            return False
        return await self.client.reboot()

    async def async_reset_total_energy(self) -> bool:
        """Reset the lifetime energy counter."""
        if not await self._ensure_connected():
            return False
        return await self.client.reset_total_energy()

    async def async_configure_wifi(self, ssid: str, password: str) -> bool:
        """Configure the charger's WiFi."""
        if not await self._ensure_connected():
            return False
        return await self.client.wifi_configure(ssid, password)

    @property
    def run_mode(self) -> int:
        return self.charger_config.run_mode

    @property
    def energy_lifetime_kwh(self) -> float:
        """Monotonic lifetime energy total (kWh) for the Energy Dashboard."""
        return round(self._energy_total_kwh, 3)

    def restore_energy_total(self, value: float) -> None:
        """Restore the lifetime energy accumulator after a HA restart."""
        if not self._energy_restored and value is not None and value >= 0:
            self._energy_total_kwh = float(value)
            self._energy_restored = True
            _LOGGER.debug("Restored lifetime energy total: %.3f kWh", value)

    @property
    def bluetooth_rssi(self) -> int | None:
        """Current BLE signal strength (dBm) from the HA Bluetooth stack.

        This reads the last advertisement seen by Home Assistant — it does not
        require a request to the charger. Returns None if unavailable.
        """
        if async_last_service_info is None:
            return None
        try:
            info = async_last_service_info(self.hass, self.mac, connectable=True)
            if info is not None and info.rssi is not None:
                return int(info.rssi)
        except Exception:  # noqa: BLE001
            pass
        return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    @property
    def is_charging(self) -> bool:
        if not self.data:
            return False
        return self.data["status"].charge_state == 3

    @property
    def charge_state(self) -> int:
        if not self.data:
            return 0
        return self.data["status"].charge_state

    @property
    def max_amps(self) -> float:
        return self._max_amps

    @property
    def hw_max_amps(self) -> float:
        """Physical hardware maximum current (from CMD 47)."""
        return self.charger_config.max_amps_hw or 32.0
