"""Preview camera: a still from the camera so each device is easy to recognise."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import XMEyeConfigEntry, XMEyeCoordinator
from .dvrip import DVRIPError
from .entity import XMEyeEntity, section_item

_LOGGER = logging.getLogger(__name__)
MIN_INTERVAL = 10  # seconds between fetches; the UI asks every few seconds


async def async_setup_entry(hass: HomeAssistant, entry: XMEyeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(PreviewCamera(coord, ch) for ch in range(coord.channels))


class PreviewCamera(XMEyeEntity, Camera):
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coord: XMEyeCoordinator, ch: int) -> None:
        XMEyeEntity.__init__(self, coord, ch, "preview", "Preview")
        Camera.__init__(self)
        self._attr_entity_category = None
        self._lock = asyncio.Lock()
        self._image: bytes | None = None
        self._fetched = 0.0
        self._method: str | None = None  # "dvrip" or "rtsp" once one has worked

    @property
    def _rtsp_port(self) -> int:
        rtsp = section_item(self.coordinator, "rtsp", 0) or {}
        port = rtsp.get("Port") if isinstance(rtsp, dict) else None
        return port if isinstance(port, int) and port > 0 else 554

    def _rtsp_url(self) -> str:
        data = self.coordinator.config_entry.data
        user = quote(data[CONF_USERNAME], safe="")
        password = quote(data.get(CONF_PASSWORD, ""), safe="")
        return (f"rtsp://{self.coordinator.client.host}:{self._rtsp_port}/user={user}"
                f"&password={password}&channel={self._ch + 1}&stream=1.sdp?real_stream")

    async def stream_source(self) -> str | None:
        return self._rtsp_url()

    async def _from_dvrip(self) -> bytes:
        async with self.coordinator.client.session() as s:
            return await s.snapshot(self._ch)

    async def _from_rtsp(self) -> bytes | None:
        return await async_get_image(self.hass, self._rtsp_url(),
                                     extra_cmd="-rtsp_transport tcp")

    async def async_camera_image(self, width: int | None = None,
                                 height: int | None = None) -> bytes | None:
        async with self._lock:
            if self._image and time.monotonic() - self._fetched < MIN_INTERVAL:
                return self._image
            image: bytes | None = None
            if self._method in (None, "dvrip"):
                try:
                    image = await self._from_dvrip()
                    self._method = "dvrip"
                except DVRIPError as err:
                    _LOGGER.debug("DVRIP snapshot unavailable for %s: %s",
                                  self.coordinator.client.host, err)
            if image is None:
                image = await self._from_rtsp()
                if image and self._method is None:
                    self._method = "rtsp"
            if image:
                self._image = image
                self._fetched = time.monotonic()
            return self._image
