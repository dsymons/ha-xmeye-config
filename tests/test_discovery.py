import asyncio, json, socket, struct
from unittest.mock import patch
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xmeye_config.const import DOMAIN
from custom_components.xmeye_config.discovery import FoundCamera, broadcast_search, sweep_subnet
from custom_components.xmeye_config.dvrip import HEADER
from .fake_camera import FakeCamera


class Responder(asyncio.DatagramProtocol):
    """Answers the 1530 search like a camera at 192.168.6.175."""
    def connection_made(self, t): self.t = t
    def datagram_received(self, data, addr):
        if HEADER.unpack(data[:20])[4] != 1530: return
        body = json.dumps({"NetWork.NetCommon": {"HostIP": "0xAF06A8C0", "MAC": "00:12:34:56:78:9a",
            "HostName": "LocalHost", "TCPPort": 34567}}).encode()
        self.t.sendto(HEADER.pack(255, 0, 0, 0, 1531, len(body)) + body + b"\x00", addr)


def free_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


async def test_broadcast_protocol():
    loop = asyncio.get_running_loop()
    t, _ = await loop.create_datagram_endpoint(Responder, local_addr=("127.0.0.1", 0))
    rport = t.get_extra_info("sockname")[1]
    try:
        found = await broadcast_search(timeout=0.4, target="127.0.0.1", port=rport, listen_port=free_udp())
    finally:
        t.close()
    assert found == [FoundCamera(host="192.168.6.175", port=34567, mac="00:12:34:56:78:9a",
                                 name="LocalHost", method="broadcast")]


async def test_sweep_finds_dvrip_only():
    cam = await FakeCamera().start()
    other = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)  # non-DVRIP port
    try:
        assert [c.host for c in await sweep_subnet("127.0.0.1/32", port=cam.port)] == ["127.0.0.1"]
        assert await sweep_subnet("127.0.0.1/32", port=other.sockets[0].getsockname()[1]) == []
        with pytest.raises(ValueError):
            await sweep_subnet("10.0.0.0/16")
    finally:
        await cam.stop(); other.close()


async def test_search_flow(hass: HomeAssistant):
    cam = await FakeCamera().start()
    found = [FoundCamera(host="127.0.0.1", port=cam.port, mac="aa", name="LocalHost")]
    try:
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert r["type"] is FlowResultType.MENU
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "search"})
        with patch("custom_components.xmeye_config.config_flow.broadcast_search", return_value=[]):
            r = await hass.config_entries.flow.async_configure(r["flow_id"], {"subnet": ""})
            assert r["errors"] == {"base": "no_devices_found"}
            r = await hass.config_entries.flow.async_configure(r["flow_id"], {"subnet": "nonsense"})
            assert r["errors"] == {"subnet": "invalid_subnet"}
        with patch("custom_components.xmeye_config.config_flow.broadcast_search", return_value=found):
            r = await hass.config_entries.flow.async_configure(r["flow_id"], {"subnet": ""})
        assert r["step_id"] == "pick"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"camera": "127.0.0.1"})
        assert r["step_id"] == "credentials"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"username": "admin", "password": "x"})
        assert r["errors"] == {"base": "invalid_auth"}
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"username": "admin", "password": ""})
        assert r["type"] is FlowResultType.CREATE_ENTRY and r["data"]["port"] == cam.port
        await hass.async_block_till_done()
    finally:
        await cam.stop()


async def test_sweep_in_flow_skips_configured(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id="z", data={"host": "10.0.0.5", "port": 1,
        "username": "admin", "password": ""}).add_to_hass(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "search"})
    with patch("custom_components.xmeye_config.config_flow.broadcast_search", return_value=[]), \
         patch("custom_components.xmeye_config.config_flow.sweep_subnet",
               return_value=[FoundCamera(host="10.0.0.5", method="sweep"),
                             FoundCamera(host="10.0.0.6", method="sweep")]):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"subnet": "10.0.0.0/24"})
    opts = r["data_schema"].schema["camera"].config["options"]
    assert [o["value"] for o in opts] == ["10.0.0.6"]


async def test_background_discovery_creates_card(hass: HomeAssistant):
    cam = await FakeCamera().start()
    other = await FakeCamera().start()
    try:
        entry = MockConfigEntry(domain=DOMAIN, unique_id="abc123def456", data={"host": "127.0.0.1",
            "port": cam.port, "username": "admin", "password": ""})
        entry.add_to_hass(hass)
        found = [FoundCamera(host="127.0.0.1", port=cam.port, mac="aa"),        # already added
                 FoundCamera(host="127.0.0.2", port=other.port, mac="bb", name="Garage")]
        with patch("custom_components.xmeye_config.broadcast_search", return_value=found):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert len(flows) == 1
        f = flows[0]
        assert f["context"]["source"] == config_entries.SOURCE_INTEGRATION_DISCOVERY
        assert f["context"]["title_placeholders"]["name"] == "Garage (127.0.0.2)"
        assert f["step_id"] == "discovery_confirm"
    finally:
        await cam.stop(); await other.stop()
