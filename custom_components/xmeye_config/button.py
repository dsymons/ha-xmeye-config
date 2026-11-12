"""Buttons: reboot, set clock from Home Assistant."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import XMEyeConfigEntry, XMEyeCoordinator
from .dvrip import DVRIPError
from .entity import XMEyeEntity


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities([RebootButton(coord), SyncTimeButton(coord)])


class RebootButton(XMEyeEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coord: XMEyeCoordinator) -> None:
        super().__init__(coord, 0, "reboot", "Reboot")

    async def async_press(self) -> None:
        try:
            async with self.coordinator.client.session() as s:
                await s.reboot()
        except DVRIPError as err:
            raise HomeAssistantError(f"Reboot failed: {err}") from err


class SyncTimeButton(XMEyeEntity, ButtonEntity):
    def __init__(self, coord: XMEyeCoordinator) -> None:
        super().__init__(coord, 0, "sync_time", "Set clock from Home Assistant")

    async def async_press(self) -> None:
        try:
            async with self.coordinator.client.session() as s:
                await s.set_time(dt_util.now().replace(tzinfo=None))
        except DVRIPError as err:
            raise HomeAssistantError(f"Setting time failed: {err}") from err
