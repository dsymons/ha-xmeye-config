"""Shared entity base and catalogue-driven entity builder."""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .catalog import FIELDS, Field, from_ha, kind_ok, to_ha
from .const import DOMAIN
from .coordinator import XMEyeCoordinator
from .dvrip import DVRIPSession


def get_path(data: Any, path: Sequence[Any]) -> Any:
    for part in path:
        try:
            data = data[part]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def set_path(data: Any, path: Sequence[Any], value: Any) -> bool:
    parent = get_path(data, path[:-1])
    if parent is None:
        return False
    try:
        parent[path[-1]] = value
    except (KeyError, IndexError, TypeError):
        return False
    return True


def section_item(coord: XMEyeCoordinator, key: str, ch: int) -> Any:
    values = (coord.data or {}).get(key) or []
    return values[ch] if ch < len(values) else None


def fields_for(coord: XMEyeCoordinator, platform: str) -> Iterator[tuple[Field, int]]:
    """Yield (field, channel) pairs this camera actually has, with the right type."""
    for fld in FIELDS:
        if fld.platform != platform:
            continue
        for ch in range(coord.channels):
            if kind_ok(fld.kind, get_path(section_item(coord, fld.section, ch), fld.path)):
                yield fld, ch


class XMEyeEntity(CoordinatorEntity[XMEyeCoordinator]):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: XMEyeCoordinator, ch: int, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._ch = ch
        entry = coordinator.config_entry
        if coordinator.channels > 1:
            name = f"Channel {ch + 1} {name[0].lower()}{name[1:]}"
        self._attr_name = name
        suffix = key if ch == 0 else f"ch{ch}_{key}"
        self._attr_unique_id = f"{entry.unique_id}_{suffix}"
        info = coordinator.system_info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer="Xiongmai",
            model=info.get("HardWare") or info.get("DeviceModel"),
            sw_version=info.get("SoftWareVersion"),
            hw_version=info.get("HardWareVersion"),
            serial_number=info.get("SerialNo"),
            configuration_url=f"http://{coordinator.client.host}/",
        )


class FieldEntity(XMEyeEntity):
    """Entity bound to one catalogue Field on one channel."""

    def __init__(self, coordinator: XMEyeCoordinator, fld: Field, ch: int) -> None:
        super().__init__(coordinator, ch, fld.key, fld.name)
        self.field = fld
        self._attr_entity_registry_enabled_default = fld.enabled
        if fld.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if fld.icon:
            self._attr_icon = fld.icon

    @property
    def raw_value(self) -> Any:
        return get_path(section_item(self.coordinator, self.field.section, self._ch),
                        self.field.path)

    @property
    def ha_value(self) -> Any:
        raw = self.raw_value
        return None if raw is None else to_ha(self.field.kind, raw, self.field.options)

    @property
    def available(self) -> bool:
        return super().available and self.raw_value is not None

    async def write(self, value: Any) -> None:
        raw = from_ha(self.field.kind, value, self.field.options)
        paths = (self.field.path, *self.field.mirror)

        def mutate(item: Any, _s: DVRIPSession) -> None:
            for path in paths:
                set_path(item, path, raw)

        await self.coordinator.async_modify(self.field.section, self._ch, mutate)
