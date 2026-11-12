"""Switch entities from the catalogue, plus the guarded IP filter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .catalog import ip_to_hex
from .coordinator import XMEyeConfigEntry, XMEyeCoordinator
from .dvrip import DVRIPSession
from .entity import FieldEntity, XMEyeEntity, fields_for, section_item


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    entities: list[SwitchEntity] = [FieldSwitch(coord, f, ch) for f, ch in fields_for(coord, "switch")]
    if isinstance((section_item(coord, "ipfilter", 0) or {}).get("Enable"), bool):
        entities.append(IPFilterSwitch(coord))
    async_add_entities(entities)


class FieldSwitch(FieldEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        return self.ha_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.write(False)


class IPFilterSwitch(XMEyeEntity, SwitchEntity):
    """Allow-list switch. Refuses to enable unless Home Assistant is on the list."""

    def __init__(self, coord: XMEyeCoordinator) -> None:
        super().__init__(coord, 0, "ipfilter", "IP allow list")

    @property
    def is_on(self) -> bool | None:
        return (section_item(self.coordinator, "ipfilter", 0) or {}).get("Enable")

    async def _set(self, on: bool) -> None:
        def mutate(item: dict[str, Any], s: DVRIPSession) -> None:
            if on:
                me = s.local_ip
                trusted = [t.upper() for t in item.get("Trusted") or []]
                if not me or ip_to_hex(me).upper() not in trusted:
                    raise HomeAssistantError(
                        f"Add Home Assistant's address ({me}) to the IP allow list first, "
                        "or the camera would lock Home Assistant out")
            item["Enable"] = on

        await self.coordinator.async_modify("ipfilter", 0, mutate)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
