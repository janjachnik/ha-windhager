"""Support for Windhager switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
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
    """Set up Windhager switches from a config entry."""
    coordinator = entry.runtime_data

    def switches_of(device_info: dict[str, Any]) -> list[WindhagerHotWaterBoostSwitch]:
        if device_info.get("type") != "switch":
            return []
        return [WindhagerHotWaterBoostSwitch(coordinator, device_info)]

    async_add_module_entities(entry, async_add_entities, switches_of)


class WindhagerHotWaterBoostSwitch(WindhagerEntity, SwitchEntity):
    """Switch to start and cancel a one-time domestic hot water charge."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "hot_water_boost"

    def __init__(
        self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]
    ) -> None:
        """Initialize the boost switch."""
        super().__init__(coordinator, device_info)
        self.client = self.coordinator.client
        self._circuit_prefix = f"{device_info['prefix']}{device_info['fct_id']}"

    def get_oid_value(self, path: str, default: str = "0") -> float | None:
        """The value of the circuit's datapoint at `path`."""
        return get_oid_value(self.coordinator, path, self._circuit_prefix, default)

    @property
    def is_on(self) -> bool:
        """Return true if hot water boost charge is currently active."""
        return int(self.get_oid_value("/2/16/0") or 0) == 1

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the boost switch on (start one-time charge, rule 16, level 98)."""
        await self._async_write("/2/16/0", "1")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the boost switch off (cancel one-time charge, rule 16, level 98)."""
        await self._async_write("/2/16/0", "0")
        await self.coordinator.async_request_refresh()

