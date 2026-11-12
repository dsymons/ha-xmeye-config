"""Config flow: search the network or enter a camera by hand; discovery cards."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.selector import (
    SelectOptionDict, SelectSelector, SelectSelectorConfig, SelectSelectorMode,
)

from .const import DEFAULT_PORT, DEFAULT_USERNAME, DOMAIN
from .discovery import FoundCamera, broadcast_search, sweep_subnet
from .dvrip import DVRIPAuthError, DVRIPClient, DVRIPError

_LOGGER = logging.getLogger(__name__)
CONF_SUBNET = "subnet"
CONF_CAMERA = "camera"


async def _probe(data: Mapping[str, Any]) -> dict[str, Any]:
    client = DVRIPClient(data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME],
                         data.get(CONF_PASSWORD, ""))
    async with client.session() as s:
        info = dict(await s.get_system_info())
        try:
            titles = await s.get_channel_titles()
            if titles and isinstance(titles[0], str) and titles[0].strip():
                info["_title"] = titles[0].strip()
        except DVRIPError:
            pass
        return info


def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    })


def _cred_schema(username: str = DEFAULT_USERNAME) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_USERNAME, default=username): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    })


class XMEyeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, FoundCamera] = {}
        self._chosen: FoundCamera | None = None

    # ---- shared --------------------------------------------------------------

    def _configured_hosts(self) -> set[str]:
        return {e.data.get(CONF_HOST) for e in self._async_current_entries(include_ignore=False)}

    async def _check(self, data: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
        try:
            return {}, await _probe(data)
        except DVRIPAuthError as err:
            _LOGGER.warning("%s:%s refused login: %s", data[CONF_HOST], data[CONF_PORT], err)
            if err.locked:
                return {"base": "locked"}, {}
            if err.ret == 204:
                return {"base": "unknown_user"}, {}
            return {"base": "invalid_auth"}, {}
        except DVRIPError as err:
            _LOGGER.warning("Cannot set up %s:%s: %s", data[CONF_HOST], data[CONF_PORT], err)
            return {"base": "cannot_connect"}, {}

    async def _create(self, data: dict[str, Any], info: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(info.get("SerialNo") or data[CONF_HOST],
                                       raise_on_progress=False)
        self._abort_if_unique_id_configured(updates=data)
        title = info.get("_title") or info.get("HardWare") or "XMEye camera"
        return self.async_create_entry(title=f"{title} ({data[CONF_HOST]})", data=data)

    # ---- user: search or manual ------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["search", "manual"])

    async def async_step_search(self, user_input: dict[str, Any] | None = None
                                ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            found = {c.host: c for c in await broadcast_search()}
            subnet = (user_input.get(CONF_SUBNET) or "").strip()
            if subnet:
                try:
                    for c in await sweep_subnet(subnet):
                        found.setdefault(c.host, c)
                except ValueError:
                    errors[CONF_SUBNET] = "invalid_subnet"
            configured = self._configured_hosts()
            self._found = {h: c for h, c in found.items() if h not in configured}
            if not errors:
                if self._found:
                    return await self.async_step_pick()
                errors["base"] = "no_devices_found"
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Optional(CONF_SUBNET, default=""): str}),
            errors=errors,
        )

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._chosen = self._found[user_input[CONF_CAMERA]]
            return await self.async_step_credentials()
        options = [
            SelectOptionDict(value=c.host, label=" · ".join(
                p for p in (c.host, c.name, c.mac) if p))
            for c in self._found.values()
        ]
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({vol.Required(CONF_CAMERA): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST))}),
            description_placeholders={"count": str(len(options))},
        )

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None
                                     ) -> ConfigFlowResult:
        assert self._chosen is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_HOST: self._chosen.host, CONF_PORT: self._chosen.port, **user_input}
            errors, info = await self._check(data)
            if not errors:
                return await self._create(data, info)
        return self.async_show_form(
            step_id="credentials", data_schema=_cred_schema(), errors=errors,
            description_placeholders={"host": self._chosen.host},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None
                                ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, info = await self._check(user_input)
            if not errors:
                return await self._create(user_input, info)
        return self.async_show_form(step_id="manual", data_schema=_schema(user_input or {}),
                                    errors=errors)

    # ---- background discovery ---------------------------------------------------

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]
                                               ) -> ConfigFlowResult:
        host = discovery_info[CONF_HOST]
        self._async_abort_entries_match({CONF_HOST: host})
        mac = discovery_info.get("mac")
        await self.async_set_unique_id(f"mac_{mac}" if mac else f"host_{host}")
        self._abort_if_unique_id_configured()
        self._chosen = FoundCamera(host=host, port=discovery_info.get(CONF_PORT, DEFAULT_PORT),
                                   mac=mac, name=discovery_info.get("name"))
        self.context["title_placeholders"] = {"name": f"{self._chosen.name or 'Camera'} ({host})"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None
                                           ) -> ConfigFlowResult:
        assert self._chosen is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_HOST: self._chosen.host, CONF_PORT: self._chosen.port, **user_input}
            errors, info = await self._check(data)
            if not errors:
                return await self._create(data, info)
        return self.async_show_form(
            step_id="discovery_confirm", data_schema=_cred_schema(), errors=errors,
            description_placeholders={"host": self._chosen.host},
        )

    # ---- reconfigure / reauth -----------------------------------------------------

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None
                                     ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, _ = await self._check(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(step_id="reconfigure",
                                    data_schema=_schema(user_input or entry.data), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reconfigure_auth()

    async def async_step_reconfigure_auth(self, user_input: dict[str, Any] | None = None
                                          ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            errors, _ = await self._check(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(step_id="reconfigure_auth",
                                    data_schema=_cred_schema(entry.data[CONF_USERNAME]),
                                    errors=errors)
