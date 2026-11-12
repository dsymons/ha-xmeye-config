"""Diagnostics download: everything the camera reports, to help support new models."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .catalog import DIAGNOSTIC_ABILITIES, EXTRA_DIAGNOSTIC_SECTIONS, FIELDS, SECTIONS
from .coordinator import XMEyeConfigEntry
from .dvrip import DVRIPCommandError, DVRIPError

TO_REDACT = {CONF_PASSWORD, "PassWord", "Password", "SerialNo", "MAC", "UserName",
             "PassWd", "Pwd", "Key", "DDNSKey", "EmailPassword"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant,
                                             entry: XMEyeConfigEntry) -> dict[str, Any]:
    coord = entry.runtime_data
    extra: dict[str, Any] = {}
    abilities: dict[str, Any] = {}
    try:
        async with coord.client.session() as s:
            for name in EXTRA_DIAGNOSTIC_SECTIONS:
                try:
                    extra[name] = await s.get_config(name)
                except DVRIPCommandError as err:
                    extra[name] = f"unavailable ({err.ret})"
            for name in DIAGNOSTIC_ABILITIES:
                try:
                    abilities[name] = await s.get_ability(name)
                except DVRIPCommandError as err:
                    abilities[name] = f"unavailable ({err.ret})"
    except DVRIPError as err:
        extra = {"error": str(err)}

    supported = coord.supported or set()
    return async_redact_data({
        "entry": dict(entry.data),
        "system_info": coord.system_info,
        "channels": coord.channels,
        "supported_sections": sorted(supported),
        "unsupported_sections": sorted(set(SECTIONS) - supported),
        "catalogue_fields": len(FIELDS),
        "polled_data": coord.data,
        "extra_sections": extra,
        "abilities": abilities,
    }, TO_REDACT)
