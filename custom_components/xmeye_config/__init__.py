"""XMEye Camera Config: local configuration of Xiongmai (XMEye/iCSee) cameras."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from datetime import timedelta

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY

from .discovery import broadcast_search
from .const import ATTR_CONFIG_ENTRY, ATTR_DATA, ATTR_KIND, ATTR_NAME, DOMAIN
from .coordinator import XMEyeConfigEntry, XMEyeCoordinator
from .dvrip import DVRIPClient, DVRIPError

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR,
             Platform.SWITCH, Platform.TEXT]
DISCOVERY_INTERVAL = timedelta(minutes=30)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GET_SCHEMA = vol.Schema({
    vol.Required(ATTR_CONFIG_ENTRY): cv.string,
    vol.Required(ATTR_NAME): cv.string,
    vol.Optional(ATTR_KIND, default="config"): vol.In(["config", "ability"]),
})
SET_SCHEMA = vol.Schema({
    vol.Required(ATTR_CONFIG_ENTRY): cv.string,
    vol.Required(ATTR_NAME): cv.string,
    vol.Required(ATTR_DATA): vol.Any(dict, list),
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    def _coordinator(call: ServiceCall) -> XMEyeCoordinator:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY])
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("Choose a loaded XMEye Camera Config entry")
        return entry.runtime_data

    async def get_config(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(call)
        name = call.data[ATTR_NAME]
        try:
            async with coord.client.session() as s:
                if call.data[ATTR_KIND] == "ability":
                    value = await s.get_ability(name)
                else:
                    value = await s.get_config(name)
        except DVRIPError as err:
            raise HomeAssistantError(str(err)) from err
        return {"name": name, "value": value}

    async def set_config(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(call)
        name = call.data[ATTR_NAME]
        try:
            async with coord.client.session() as s:
                ret = await s.set_config(name, call.data[ATTR_DATA])
        except DVRIPError as err:
            raise HomeAssistantError(str(err)) from err
        await coord.async_request_refresh()
        return {"name": name, "ret": ret, "restart_required": ret == 150}

    hass.services.async_register(DOMAIN, "get_config", get_config, schema=GET_SCHEMA,
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "set_config", set_config, schema=SET_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    async def scan(_now: Any = None) -> None:
        configured = {e.data.get(CONF_HOST) for e in hass.config_entries.async_entries(DOMAIN)}
        for cam in await broadcast_search():
            if cam.host in configured:
                continue
            discovery_flow.async_create_flow(
                hass, DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_HOST: cam.host, CONF_PORT: cam.port, "mac": cam.mac, "name": cam.name},
            )

    async_at_started(hass, scan)
    async_track_time_interval(hass, scan, DISCOVERY_INTERVAL, cancel_on_shutdown=True)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry) -> bool:
    data: dict[str, Any] = entry.data
    client = DVRIPClient(data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME],
                         data.get(CONF_PASSWORD, ""))
    coordinator = XMEyeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XMEyeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
