"""Select entities from the catalogue."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import XMEyeConfigEntry
from .entity import FieldEntity, fields_for


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(FieldSelect(coord, f, ch) for f, ch in fields_for(coord, "select"))


class FieldSelect(FieldEntity, SelectEntity):
    @property
    def options(self) -> list[str]:
        current = self.ha_value
        stream = self.field.extra.get("resolution")
        if stream:
            return self.coordinator.resolution_options(stream, current)
        opts = list((self.field.options or {}).keys())
        if current is not None and current not in opts:
            opts.append(current)  # unknown firmware value: keep it selectable
        return opts

    @property
    def current_option(self) -> str | None:
        return self.ha_value

    async def async_select_option(self, option: str) -> None:
        await self.write(option)
