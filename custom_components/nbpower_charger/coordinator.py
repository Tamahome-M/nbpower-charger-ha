"""DataUpdateCoordinator for NBPower EV Charger."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .nbpower_ble import NBPowerBLEClient, NBPowerStatus, NBPowerMeterData, NBPowerDeviceInfo
from .const import DOMAIN, DEFAULT_MAX_AMPS

_LOGGER = logging.getLogger(__name__)


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
        self._max_amps: float = DEFAULT_MAX_AMPS
        self._reconnect_lock = asyncio.Lock()

    # ── Connection management ──────────────────────────────────────────────────

    async def async_connect(self) -> None:
        """Connect and fetch initial device info."""
        await self.client.connect(timeout=15.0)
        self.device_info = await self.client.get_device_info()
        _LOGGER.info(
            "NBPower charger connected: %s (fw=%d, num=%d)",
            self.mac,
            self.device_info.firmware_version,
            self.device_info.device_num,
        )

    async def async_disconnect(self) -> None:
        """Disconnect cleanly."""
        await self.client.disconnect()

    async def _ensure_connected(self) -> bool:
        """Reconnect if needed. Returns True if connected."""
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
        """Fetch all data from the charger. Called by HA scheduler."""
        if not await self._ensure_connected():
            raise UpdateFailed("Bluetooth connection unavailable")

        try:
            status: NBPowerStatus = await self.client.get_status()
            meter: NBPowerMeterData = await self.client.get_meter_data()
            timing: dict = await self.client.get_charging_time()

            return {
                "status": status,
                "meter": meter,
                "timing": timing,
                "available": True,
            }
        except Exception as ex:
            _LOGGER.error("Poll error: %s", ex)
            # Mark as disconnected so next poll triggers reconnect
            self.client._connected = False
            raise UpdateFailed(f"Error communicating with charger: {ex}") from ex

    # ── Control actions ────────────────────────────────────────────────────────

    async def async_start_charging(self, max_amps: float | None = None) -> bool:
        """Start charging. Uses configured max_amps if not specified."""
        if not await self._ensure_connected():
            _LOGGER.error("Cannot start charging: not connected")
            return False
        amps = max_amps if max_amps is not None else self._max_amps
        result = await self.client.start_charging(max_amps=amps)
        if result:
            await self.async_request_refresh()
        return result

    async def async_stop_charging(self) -> bool:
        """Stop charging."""
        if not await self._ensure_connected():
            _LOGGER.error("Cannot stop charging: not connected")
            return False
        result = await self.client.stop_charging()
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_max_amps(self, amps: float) -> None:
        """Update the default max current setting."""
        self._max_amps = max(6.0, min(32.0, amps))

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
