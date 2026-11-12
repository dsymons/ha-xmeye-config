"""Polling coordinator: discovers what the camera supports, then polls it."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .catalog import SECTIONS, Section
from .const import DOMAIN, FALLBACK_RESOLUTIONS, RESOLUTION_BITS, SCAN_INTERVAL_SECONDS
from .dvrip import (
    DVRIPAuthError, DVRIPClient, DVRIPCommandError, DVRIPError, DVRIPSession,
)

_LOGGER = logging.getLogger(__name__)

type XMEyeConfigEntry = ConfigEntry["XMEyeCoordinator"]
# data[section_key] = [value for channel 0, channel 1, ...]; data["titles"] = [...]
type CameraData = dict[str, list[Any]]
Mutator = Callable[[Any, DVRIPSession], Awaitable[None] | None]


def _decode_mask(mask: Any) -> list[str]:
    try:
        value = int(mask, 16) if isinstance(mask, str) else int(mask)
    except (TypeError, ValueError):
        return []
    return [name for bit, name in enumerate(RESOLUTION_BITS) if value & (1 << bit)]


class XMEyeCoordinator(DataUpdateCoordinator[CameraData]):
    config_entry: XMEyeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: XMEyeConfigEntry,
                 client: DVRIPClient) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.system_info: dict[str, Any] = {}
        self.capability: Any = None
        self.channels = 1
        self.supported: set[str] | None = None  # None until first poll has probed
        self.titles_supported = False

    async def _async_setup(self) -> None:
        try:
            async with self.client.session() as s:
                self.system_info = await s.get_system_info()
                try:
                    self.capability = await s.get_ability("EncodeCapability")
                except DVRIPCommandError:
                    self.capability = None
        except DVRIPAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DVRIPError as err:
            raise UpdateFailed(str(err)) from err
        try:
            self.channels = max(1, int(self.system_info.get("VideoInChannel") or 1))
        except (TypeError, ValueError):
            self.channels = 1

    async def _read_section(self, s: DVRIPSession, sec: Section) -> list[Any] | None:
        """Return per-channel values, or None if the camera lacks the section."""
        if sec.channels == "indexed":
            values: list[Any] = []
            for ch in range(self.channels):
                try:
                    values.append(await s.get_config(sec.wire_name(ch)))
                except DVRIPCommandError:
                    if ch == 0:
                        return None
                    values.append(None)
            return values
        try:
            value = await s.get_config(sec.name)
        except DVRIPCommandError:
            return None
        if sec.channels == "list":
            return value if isinstance(value, list) else [value]
        return [value]

    async def _async_update_data(self) -> CameraData:
        data: CameraData = {}
        probing = self.supported is None
        found: set[str] = set()
        try:
            async with self.client.session() as s:
                for key, sec in SECTIONS.items():
                    if not probing and key not in self.supported:
                        continue
                    values = await self._read_section(s, sec)
                    if values is not None:
                        data[key] = values
                        found.add(key)
                if probing or self.titles_supported:
                    try:
                        data["titles"] = list(await s.get_channel_titles())
                        self.titles_supported = True
                    except DVRIPCommandError:
                        self.titles_supported = False
        except DVRIPAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DVRIPError as err:
            raise UpdateFailed(str(err)) from err
        if probing:
            self.supported = found
            _LOGGER.debug("%s supports sections: %s", self.client.host, sorted(found))
        return data

    # ---- helpers for entities ----------------------------------------------

    @property
    def max_fps(self) -> int:
        loc = (self.data or {}).get("location") or [{}]
        return 30 if (loc[0] or {}).get("VideoFormat") == "NTSC" else 25

    def resolution_options(self, stream: str, current: str | None) -> list[str]:
        options: list[str] = []
        cap = self.capability if isinstance(self.capability, dict) else {}
        want = "Main" if stream == "MainFormat" else "Extra"
        for info in cap.get("EncodeInfo") or []:
            if want in str(info.get("StreamType", "")):
                options = _decode_mask(info.get("ResolutionMask"))
                break
        if not options or (current and current not in options):
            options = list(FALLBACK_RESOLUTIONS[stream])
        if current and current not in options:
            options.append(current)
        return options

    async def async_modify(self, key: str, ch: int, mutate: Mutator) -> None:
        """Read one channel's section fresh, change it, write it back, re-read."""
        sec = SECTIONS[key]
        name = sec.wire_name(ch)
        try:
            async with self.client.session() as s:
                current = await s.get_config(name)
                updated = copy.deepcopy(current)
                target = updated[ch] if sec.channels == "list" else updated
                result = mutate(target, s)
                if result is not None:
                    await result
                await s.set_config(name, updated)
                check = await s.get_config(name)
        except DVRIPCommandError as err:
            raise HomeAssistantError(f"Camera rejected the change: {err}") from err
        except DVRIPError as err:
            raise HomeAssistantError(f"Could not reach camera: {err}") from err
        if check != updated:
            _LOGGER.warning("Camera accepted %s but did not apply every value", name)
        new = dict(self.data or {})
        values = list(new.get(key) or [None] * self.channels)
        if sec.channels == "list":
            values = check if isinstance(check, list) else values
        elif sec.channels == "indexed":
            while len(values) <= ch:
                values.append(None)
            values[ch] = check
        else:
            values = [check]
        new[key] = values
        self.async_set_updated_data(new)

    async def async_set_title(self, ch: int, title: str) -> None:
        try:
            async with self.client.session() as s:
                titles = list(await s.get_channel_titles())
                while len(titles) <= ch:
                    titles.append("")
                titles[ch] = title
                await s.set_channel_titles(titles)
                titles = list(await s.get_channel_titles())
        except DVRIPError as err:
            raise HomeAssistantError(f"Could not set camera name: {err}") from err
        new = dict(self.data or {})
        new["titles"] = titles
        self.async_set_updated_data(new)
