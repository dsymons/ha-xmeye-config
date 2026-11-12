"""Text entities: catalogue fields plus NTP server, camera name, IP allow list."""

from __future__ import annotations

import ipaddress
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .catalog import _hex_ip, ip_to_hex
from .coordinator import XMEyeConfigEntry, XMEyeCoordinator
from .dvrip import DVRIPSession
from .entity import FieldEntity, XMEyeEntity, fields_for, get_path, section_item


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    entities: list[TextEntity] = [FieldText(coord, f, ch) for f, ch in fields_for(coord, "text")]
    if isinstance(get_path(section_item(coord, "ntp", 0), ("Server", "Name")), str):
        entities.append(NtpServerText(coord))
    if coord.titles_supported:
        entities += [CameraNameText(coord, ch) for ch in range(coord.channels)]
    if isinstance((section_item(coord, "ipfilter", 0) or {}).get("Trusted"), list):
        entities.append(AllowListText(coord))
    async_add_entities(entities)


class FieldText(FieldEntity, TextEntity):
    _attr_native_max = 64

    @property
    def native_value(self) -> str | None:
        return self.ha_value

    async def async_set_value(self, value: str) -> None:
        await self.write(value.strip())


class NtpServerText(XMEyeEntity, TextEntity):
    _attr_native_max = 64

    def __init__(self, coord: XMEyeCoordinator) -> None:
        super().__init__(coord, 0, "ntp_server", "NTP server")

    @property
    def native_value(self) -> str | None:
        return get_path(section_item(self.coordinator, "ntp", 0), ("Server", "Name"))

    async def async_set_value(self, value: str) -> None:
        value = value.strip()

        def mutate(item: dict[str, Any], _s: DVRIPSession) -> None:
            item.setdefault("Server", {})["Name"] = value
            port = item["Server"].get("Port", 123)
            # Only server, so the camera can't fall back to others.
            if "NtpServerList" in item:
                item["NtpServerList"] = [{"Port": port, "Server": value}]

        await self.coordinator.async_modify("ntp", 0, mutate)


class CameraNameText(XMEyeEntity, TextEntity):
    _attr_native_max = 32

    def __init__(self, coord: XMEyeCoordinator, ch: int) -> None:
        super().__init__(coord, ch, "camera_name", "Camera name")

    @property
    def native_value(self) -> str | None:
        titles = (self.coordinator.data or {}).get("titles") or []
        return titles[self._ch] if self._ch < len(titles) else None

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_title(self._ch, value.strip())


class AllowListText(XMEyeEntity, TextEntity):
    """Comma-separated IPv4 addresses allowed when the IP allow list is on."""

    _attr_native_max = 255

    def __init__(self, coord: XMEyeCoordinator) -> None:
        super().__init__(coord, 0, "ipfilter_trusted", "IP allow list addresses")

    @property
    def native_value(self) -> str | None:
        trusted = (section_item(self.coordinator, "ipfilter", 0) or {}).get("Trusted") or []
        ips = [_hex_ip(t) for t in trusted if isinstance(t, str) and int(t, 16)]
        return ", ".join(ips)

    async def async_set_value(self, value: str) -> None:
        try:
            ips = [str(ipaddress.IPv4Address(p.strip())) for p in value.split(",") if p.strip()]
        except ValueError as err:
            raise HomeAssistantError(f"Not a valid IPv4 address list: {err}") from err

        def mutate(item: dict[str, Any], s: DVRIPSession) -> None:
            if item.get("Enable") and s.local_ip not in ips:
                raise HomeAssistantError(
                    f"The allow list is on, so it must keep Home Assistant ({s.local_ip})")
            size = max(len(item.get("Trusted") or []), len(ips))
            item["Trusted"] = [ip_to_hex(ip) for ip in ips] + ["0x00000000"] * (size - len(ips))

        await self.coordinator.async_modify("ipfilter", 0, mutate)
