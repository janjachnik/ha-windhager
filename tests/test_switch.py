"""Tests for the Windhager hot water boost switch."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.exceptions import CannotConnect, InvalidAuth, WriteFailed

SWITCH_DEVICE = {
    "id": "circuit_dhw_boost",
    "name": "Heating circuit Hot Water Boost",
    "key": "hot_water_boost",
    "type": "switch",
    "prefix": "/1/15",
    "fct_id": "/0",
    "device_id": "circuit_dhw",
    "device_name": "Heating circuit Hot Water",
    "oid": "/1/15/0/2/16/0",
}
SWITCH_OIDS = {
    "/1/15/0/2/16/0": "0",
}


async def set_up_switch(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: MagicMock,
    oids: dict[str, str | None] = SWITCH_OIDS,
) -> None:
    client.fetch_all.return_value = {
        "devices": [SWITCH_DEVICE],
        "oids": oids,
    }
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(("boost_value", "expected_state"), [("1", "on"), ("0", "off")])
async def test_boost_switch_state(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, boost_value: str, expected_state: str
) -> None:
    await set_up_switch(hass, entry, client, oids={"/1/15/0/2/16/0": boost_value})

    state = hass.states.get("switch.heating_circuit_hot_water_boost")
    assert state is not None
    assert state.state == expected_state


async def test_boost_switch_turn_on(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_switch(hass, entry, client)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.heating_circuit_hot_water_boost"},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/2/16/0", "1")


async def test_boost_switch_turn_off(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_switch(hass, entry, client, oids={"/1/15/0/2/16/0": "1"})

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.heating_circuit_hot_water_boost"},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/2/16/0", "0")


@pytest.mark.parametrize(
    ("failure", "translation_key"),
    [
        (WriteFailed("/1/15/0/2/16/0", 500), "write_refused"),
        (CannotConnect("no answer"), "write_cannot_connect"),
        (InvalidAuth("refused"), "write_auth_failed"),
    ],
)
async def test_a_failed_switch_write_fails_with_reason(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, failure: Exception, translation_key: str
) -> None:
    await set_up_switch(hass, entry, client)
    client.update.side_effect = failure

    with pytest.raises(HomeAssistantError) as failed:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.heating_circuit_hot_water_boost"},
            blocking=True,
        )

    assert failed.value.translation_domain == "windhager"
    assert failed.value.translation_key == translation_key


async def test_a_switch_write_refusing_password_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_switch(hass, entry, client)
    client.update.side_effect = InvalidAuth("refused")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.heating_circuit_hot_water_boost"},
            blocking=True,
        )
    await hass.async_block_till_done()

    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_switch_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up_switch(hass, entry, client)

    translations = await async_get_translations(hass, language, "entity", ["windhager"])
    assert translations["component.windhager.entity.switch.hot_water_boost.name"]

