"""Support for Windhager Domestic Hot Water."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_OFF,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate import HEATER_OFF_MODES
from .const import DOMAIN
from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator
from .entity import WindhagerEntity, async_add_module_entities
from .exceptions import CannotConnect, InvalidAuth, WriteFailed
from .helpers import get_oid_value, parse_value

_LOGGER = logging.getLogger(__name__)

# One write at a time to the heater: its API answers the requests one after the other
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Windhager water heaters from a config entry, and those of a circuit added later."""
    coordinator = entry.runtime_data

    def water_heaters_of(device_info: dict[str, Any]) -> list[WindhagerWaterHeater]:
        if device_info.get("type") != "water_heater":
            return []
        return [WindhagerWaterHeater(coordinator, device_info)]

    async_add_module_entities(entry, async_add_entities, water_heaters_of)


class WindhagerWaterHeater(WindhagerEntity, WaterHeaterEntity):
    """Windhager water heater entity for domestic hot water."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = WaterHeaterEntityFeature(0)
    _attr_translation_key = "hot_water"

    def __init__(
        self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]
    ) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator, device_info)
        self.client = self.coordinator.client
        self._circuit_prefix = f"{device_info['prefix']}{device_info['fct_id']}"

    def get_oid_value(self, path: str, default: str = "0") -> float | None:
        """The value of the circuit's datapoint at `path` (group, member, instance)."""
        return get_oid_value(self.coordinator, path, self._circuit_prefix, default)

    def heater_operating_mode(self) -> int | None:
        """The operating mode of the heater, None if unknown or without a heater module."""
        data = self.coordinator.data
        for device in data.get("devices", []):
            if device.get("key") == "operating_mode":
                oid = device["oid"]
                return parse_value(data.get("oids", {}).get(oid), int, oid)
        return None

    @property
    def current_operation(self) -> str:
        """Return current operation: off when heater is off, performance when boosting, else eco."""
        if self.heater_operating_mode() in HEATER_OFF_MODES:
            return STATE_OFF
        if int(self.get_oid_value("/2/16/0") or 0) == 1:
            return STATE_PERFORMANCE
        return STATE_ECO

    @property
    def current_temperature(self) -> float | None:
        """Return the current hot water temperature."""
        return self.get_oid_value("/0/4/0")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature: the boost setpoint while boosting, else scheduled."""
        if int(self.get_oid_value("/2/16/0") or 0) == 1:
            return self.get_oid_value("/5/51/0") or self.get_oid_value("/1/4/0")
        return self.get_oid_value("/1/4/0")

    async def _async_write(self, path: str, value: str) -> None:
        """Write a datapoint of the circuit; a failure is an error the user sees."""
        try:
            await self.client.update(f"{self._circuit_prefix}{path}", value)
        except InvalidAuth as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_auth_failed"
            ) from err
        except WriteFailed as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_refused",
                translation_placeholders={"status": str(err.status)},
            ) from err
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_cannot_connect"
            ) from err

    async def boost_hot_water(self, temperature: float | None = None) -> None:
        """Trigger a one-time hot water charge release (rule 16, level 98)."""
        if temperature is not None:
            await self._async_write("/5/51/0", str(temperature))
        await self._async_write("/2/16/0", "1")
        await self.coordinator.async_request_refresh()

    async def cancel_hot_water_boost(self) -> None:
        """Cancel a one-time hot water charge release (rule 16, level 98)."""
        await self._async_write("/2/16/0", "0")
        await self.coordinator.async_request_refresh()
