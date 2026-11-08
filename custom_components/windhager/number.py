"""Support for Windhager number settings."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator
from .entity import WindhagerEntity, async_add_module_entities
from .exceptions import CannotConnect, InvalidAuth, WriteFailed
from .helpers import get_oid_value

_LOGGER = logging.getLogger(__name__)

# One write at a time to the heater: its API answers the requests one after the other
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Windhager number entities from a config entry."""
    coordinator = entry.runtime_data

    def numbers_of(device_info: dict[str, Any]) -> list[WindhagerHotWaterBoostTemperatureNumber]:
        if device_info.get("type") != "number":
            return []
        return [WindhagerHotWaterBoostTemperatureNumber(coordinator, device_info)]

    async_add_module_entities(entry, async_add_entities, numbers_of)


class WindhagerHotWaterBoostTemperatureNumber(WindhagerEntity, NumberEntity):
    """Configuration entity for the domestic hot water single charge target temperature."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 10.0
    _attr_native_max_value = 75.0
    _attr_native_step = 0.5
    _attr_translation_key = "hot_water_boost_temperature"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]
    ) -> None:
        """Initialize the boost temperature number entity."""
        super().__init__(coordinator, device_info)
        self.client = self.coordinator.client
        self._circuit_prefix = f"{device_info['prefix']}{device_info['fct_id']}"

    def get_oid_value(self, path: str, default: str = "0") -> float | None:
        """The value of the circuit's datapoint at `path`."""
        return get_oid_value(self.coordinator, path, self._circuit_prefix, default)

    @property
    def native_value(self) -> float | None:
        """Return the current single-charge target temperature setpoint."""
        return self.get_oid_value("/5/51/0")

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

    async def async_set_native_value(self, value: float) -> None:
        """Set new single-charge target temperature (rule 16, level 98)."""
        await self._async_write("/5/51/0", f"{value:.1f}")
        await self.coordinator.async_request_refresh()

