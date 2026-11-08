"""Tests for the Windhager domestic hot water boost temperature configuration entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.exceptions import CannotConnect, InvalidAuth, WriteFailed

NUMBER_DEVICE = {
    "id": "circuit_dhw_boost_temp",
    "name": "Heating circuit Hot Water Boost Temperature",
    "key": "hot_water_boost_temperature",
    "type": "number",
    "prefix": "/1/15",
    "fct_id": "/0",
    "device_id": "circuit_dhw",
    "device_name": "Heating circuit Hot Water",
    "oid": "/1/15/0/5/51/0",
    "entity_category": "config",
}
NUMBER_OIDS = {
    "/1/15/0/5/51/0": "55.0",
}


async def set_up_number(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: MagicMock,
    oids: dict[str, str | None] = NUMBER_OIDS,
) -> None:
    client.fetch_all.return_value = {
        "devices": [NUMBER_DEVICE],
        "oids": oids,
    }
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_boost_temperature_native_value(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_number(hass, entry, client)

    state = hass.states.get("number.heating_circuit_hot_water_boost_temperature")
    assert state is not None
    assert state.state == "55.0"
    assert state.attributes["min"] == 10.0
    assert state.attributes["max"] == 75.0
    assert state.attributes["step"] == 0.5
    assert state.attributes["unit_of_measurement"] == "°C"


async def test_boost_temperature_set_native_value(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_number(hass, entry, client)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.heating_circuit_hot_water_boost_temperature", "value": 58.0},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/5/51/0", "58.0")


@pytest.mark.parametrize(
    ("failure", "translation_key"),
    [
        (WriteFailed("/1/15/0/5/51/0", 500), "write_refused"),
        (CannotConnect("no answer"), "write_cannot_connect"),
        (InvalidAuth("refused"), "write_auth_failed"),
    ],
)
async def test_a_failed_number_write_fails_with_reason(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, failure: Exception, translation_key: str
) -> None:
    await set_up_number(hass, entry, client)
    client.update.side_effect = failure

    with pytest.raises(HomeAssistantError) as failed:
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.heating_circuit_hot_water_boost_temperature", "value": 58.0},
            blocking=True,
        )

    assert failed.value.translation_domain == "windhager"
    assert failed.value.translation_key == translation_key


async def test_a_number_write_refusing_password_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_number(hass, entry, client)
    client.update.side_effect = InvalidAuth("refused")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.heating_circuit_hot_water_boost_temperature", "value": 58.0},
            blocking=True,
        )
    await hass.async_block_till_done()

    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_number_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up_number(hass, entry, client)

    translations = await async_get_translations(hass, language, "entity", ["windhager"])
    assert translations["component.windhager.entity.number.hot_water_boost_temperature.name"]

