"""Read-only diagnostic sensors from the catalogue."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import XMEyeConfigEntry
from .entity import FieldEntity, fields_for


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(FieldSensor(coord, f, ch) for f, ch in fields_for(coord, "sensor"))


class FieldSensor(FieldEntity, SensorEntity):
    @property
    def native_value(self) -> Any:
        value = self.ha_value
        if isinstance(value, bool):
            return "On" if value else "Off"
        return value
