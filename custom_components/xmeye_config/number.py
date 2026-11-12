"""Number entities from the catalogue."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import XMEyeConfigEntry
from .entity import FieldEntity, fields_for


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(FieldNumber(coord, f, ch) for f, ch in fields_for(coord, "number"))


class FieldNumber(FieldEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    @property
    def native_min_value(self) -> float:
        return self.field.min

    @property
    def native_max_value(self) -> float:
        if self.field.extra.get("max_fps"):
            return self.coordinator.max_fps
        return self.field.max

    @property
    def native_step(self) -> float:
        return self.field.step

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.field.unit

    @property
    def native_value(self) -> float | None:
        return self.ha_value

    async def async_set_native_value(self, value: float) -> None:
        await self.write(int(value))
