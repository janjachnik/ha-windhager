"""The water heater entity for domestic hot water, its charging pump, and boost actions."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.components.water_heater import (
    STATE_OFF,
    STATE_PERFORMANCE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient
from custom_components.windhager.exceptions import CannotConnect, InvalidAuth, WriteFailed

CIRCUIT_DHW = {
    "id": "circuit_dhw",
    "name": "Heating circuit Hot Water",
    "key": "hot_water",
    "type": "water_heater",
    "prefix": "/1/15",
    "fct_id": "/0",
    "device_id": "circuit_dhw",
    "device_name": "Heating circuit Hot Water",
    "via_device": "circuit",
}
PUMP_SENSOR = {
    "id": "circuit_pump",
    "name": "Heating circuit Hot Water Charging Pump",
    "key": "hot_water_charging_pump",
    "type": "charging_pump",
    "prefix": "/1/15",
    "fct_id": "/0",
    "device_id": "circuit_dhw",
    "device_name": "Heating circuit Hot Water",
    "via_device": "circuit",
    "oid": "/1/15/0/1/66/0",
}
DHW_OIDS = {
    "/1/15/0/0/4/0": "52.5",
    "/1/15/0/1/4/0": "55.0",
    "/1/15/0/2/16/0": "0",
    "/1/15/0/5/51/0": "55.0",
    "/1/15/0/1/66/0": "0",
}


async def set_up_dhw(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: MagicMock,
    devices: list[dict] | None = None,
    oids: dict[str, str | None] = DHW_OIDS,
) -> None:
    client.fetch_all.return_value = {
        "devices": devices if devices is not None else [CIRCUIT_DHW, PUMP_SENSOR],
        "oids": oids,
    }
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_circuit_with_hot_water_creates_water_heater_and_pump(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(hass, entry, client)

    state = hass.states.get("water_heater.heating_circuit_hot_water")
    assert state is not None
    assert state.state == "auto"
    assert state.attributes["current_temperature"] == 52.5
    assert state.attributes["temperature"] == 55.0
    assert state.attributes["supported_features"] == 0

    pump = hass.states.get("binary_sensor.heating_circuit_hot_water_charging_pump")
    assert pump is not None
    assert pump.state == "off"


@pytest.mark.parametrize(("pump_value", "expected_state"), [("1", "on"), ("0", "off"), (None, "unknown")])
async def test_charging_pump_state(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, pump_value: str | None, expected_state: str
) -> None:
    await set_up_dhw(hass, entry, client, oids={**DHW_OIDS, "/1/15/0/1/66/0": pump_value})

    pump = hass.states.get("binary_sensor.heating_circuit_hot_water_charging_pump")
    assert pump.state == expected_state


async def test_water_heater_charging_mode_shows_performance_and_boost_target(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(
        hass,
        entry,
        client,
        oids={**DHW_OIDS, "/1/15/0/2/16/0": "1", "/1/15/0/5/51/0": "60.0"},
    )

    state = hass.states.get("water_heater.heating_circuit_hot_water")
    assert state.state == STATE_PERFORMANCE
    assert state.attributes["temperature"] == 60.0


async def test_water_heater_charging_mode_falls_back_when_boost_target_missing(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(
        hass,
        entry,
        client,
        oids={**DHW_OIDS, "/1/15/0/2/16/0": "1", "/1/15/0/5/51/0": None},
    )

    state = hass.states.get("water_heater.heating_circuit_hot_water")
    assert state.state == STATE_PERFORMANCE
    assert state.attributes["temperature"] == 55.0


async def test_water_heater_off_when_heater_is_off(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    devices = [
        CIRCUIT_DHW,
        PUMP_SENSOR,
        {
            "id": "operating_mode",
            "key": "operating_mode",
            "type": "operating_mode",
            "oid": "/1/60/0/2/59/0",
            "device_id": "biowin",
        },
    ]
    await set_up_dhw(
        hass,
        entry,
        client,
        devices=devices,
        oids={**DHW_OIDS, "/1/60/0/2/59/0": "0"},
    )

    state = hass.states.get("water_heater.heating_circuit_hot_water")
    assert state.state == STATE_OFF


async def test_boost_hot_water_starts_charge_without_temperature(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(hass, entry, client)

    await hass.services.async_call(
        "windhager",
        "boost_hot_water",
        {"entity_id": "water_heater.heating_circuit_hot_water"},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/2/16/0", "1")


async def test_boost_hot_water_sets_temperature_and_starts_charge(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(hass, entry, client)

    await hass.services.async_call(
        "windhager",
        "boost_hot_water",
        {"entity_id": "water_heater.heating_circuit_hot_water", "temperature": 58.0},
        blocking=True,
    )

    assert client.update.await_args_list == [
        call("/1/15/0/5/51/0", "58.0"),
        call("/1/15/0/2/16/0", "1"),
    ]


async def test_cancel_hot_water_boost_stops_charge(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(hass, entry, client, oids={**DHW_OIDS, "/1/15/0/2/16/0": "1"})

    await hass.services.async_call(
        "windhager",
        "cancel_hot_water_boost",
        {"entity_id": "water_heater.heating_circuit_hot_water"},
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
async def test_a_failed_boost_fails_with_reason(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, failure: Exception, translation_key: str
) -> None:
    await set_up_dhw(hass, entry, client)
    client.update.side_effect = failure

    with pytest.raises(HomeAssistantError) as failed:
        await hass.services.async_call(
            "windhager",
            "boost_hot_water",
            {"entity_id": "water_heater.heating_circuit_hot_water"},
            blocking=True,
        )

    assert failed.value.translation_domain == "windhager"
    assert failed.value.translation_key == translation_key


async def test_a_boost_refusing_password_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_dhw(hass, entry, client)
    client.update.side_effect = InvalidAuth("refused")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "windhager",
            "boost_hot_water",
            {"entity_id": "water_heater.heating_circuit_hot_water"},
            blocking=True,
        )
    await hass.async_block_till_done()

    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_boost_actions_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up_dhw(hass, entry, client)

    translations = await async_get_translations(hass, language, "services", ["windhager"])

    assert translations["component.windhager.services.boost_hot_water.name"]
    assert translations["component.windhager.services.boost_hot_water.description"]
    assert translations["component.windhager.services.boost_hot_water.fields.temperature.name"]
    assert translations["component.windhager.services.cancel_hot_water_boost.name"]
    assert translations["component.windhager.services.cancel_hot_water_boost.description"]


async def test_discovery_adds_hot_water_when_active() -> None:
    modules = [
        {
            "nodeId": 15,
            "name": "UMUMLZ",
            "neuronId": "0a0000000015",
            "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}],
        },
        {
            "nodeId": 60,
            "name": "BioWIN 2",
            "neuronId": "0a0000000060",
            "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
        },
    ]

    client = WindhagerHttpClient("192.0.2.1", "secret")

    def fetch(url: str) -> dict | list:
        if url == "/1":
            return modules
        if url == "/1/15/0/5/76/0":
            return {"value": "1"}
        return {"value": "0"}

    client.fetch = AsyncMock(side_effect=fetch)
    data = await client.fetch_all()

    types = [device["type"] for device in data["devices"]]
    assert "water_heater" in types
    assert "switch" in types
    assert "number" in types
    assert "charging_pump" in types
    assert "/1/15/0/0/4/0" in client.oids
    assert "/1/15/0/1/4/0" in client.oids
    assert "/1/15/0/2/16/0" in client.oids
    assert "/1/15/0/5/51/0" in client.oids
    assert "/1/15/0/1/66/0" in client.oids


@pytest.mark.parametrize(
    "answer",
    [{"value": "0"}, {"value": "-.-"}, ValueError("cannot fetch")],
)
async def test_discovery_does_not_add_hot_water_when_inactive_or_failing(answer: dict | Exception) -> None:
    modules = [
        {
            "nodeId": 15,
            "name": "UMUMLZ",
            "neuronId": "0a0000000015",
            "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}],
        },
        {
            "nodeId": 60,
            "name": "BioWIN 2",
            "neuronId": "0a0000000060",
            "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
        },
    ]

    client = WindhagerHttpClient("192.0.2.1", "secret")

    def fetch(url: str) -> dict | list:
        if url == "/1":
            return modules
        if url == "/1/15/0/5/76/0":
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {"value": "1"}

    client.fetch = AsyncMock(side_effect=fetch)
    data = await client.fetch_all()

    types = [device["type"] for device in data["devices"]]
    assert "water_heater" not in types
    assert "switch" not in types
    assert "number" not in types
    assert "charging_pump" not in types
    assert "/1/15/0/0/4/0" not in client.oids
