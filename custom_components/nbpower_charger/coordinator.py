"""DataUpdateCoordinator for NBPower EV Charger."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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

            return {
                "status": status,
                "meter": meter,
                "timing": timing,
                "last_session": self._cached_last_session,
                "totals": self._cached_totals,
                "network": self._cached_network,
                "available": True,
            }
        except Exception as ex:
            _LOGGER.error("Poll error: %s", ex)
            self.client._connected = False
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
