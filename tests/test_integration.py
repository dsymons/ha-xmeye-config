import asyncio
from unittest.mock import patch
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xmeye_config.const import DOMAIN
from custom_components.xmeye_config.dvrip import sofia_hash
from .fake_camera import FakeCamera


@pytest.fixture
async def cam():
    c = await FakeCamera().start()
    yield c
    await c.stop()


async def setup(hass, cam, password=""):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="abc123def456", title="Robot",
        data={"host": "127.0.0.1", "port": cam.port, "username": "admin", "password": password})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def eid(hass, uid_suffix, domain):
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"abc123def456_{uid_suffix}")


async def test_config_flow(hass: HomeAssistant, cam):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "manual"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"],
        {"host": "127.0.0.1", "port": cam.port, "username": "admin", "password": "wrong"})
    assert r["errors"] == {"base": "invalid_auth"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"],
        {"host": "127.0.0.1", "port": 1, "username": "admin", "password": ""})
    assert r["errors"] == {"base": "cannot_connect"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"],
        {"host": "127.0.0.1", "port": cam.port, "username": "admin", "password": ""})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["result"].unique_id == "abc123def456"
    assert r["title"] == "IPC_GK7205V300_S38 (127.0.0.1)"
    await hass.async_block_till_done()


async def test_entities_and_writes(hass: HomeAssistant, cam):
    await setup(hass, cam)

    res = hass.states.get(eid(hass, "MainFormat_Resolution", "select"))
    assert res.state == "3M"
    assert res.attributes["options"] == ["720P", "1080P", "3M"]
    sub = hass.states.get(eid(hass, "ExtraFormat_Resolution", "select"))
    assert sub.attributes["options"] == ["D1", "VGA"]
    fps = hass.states.get(eid(hass, "MainFormat_FPS", "number"))
    assert fps.state == "12" and fps.attributes["max"] == 25

    # writes
    await hass.services.async_call("select", "select_option",
        {"entity_id": eid(hass, "ExtraFormat_Compression", "select"), "option": "H.264"}, blocking=True)
    await hass.services.async_call("number", "set_value",
        {"entity_id": eid(hass, "ExtraFormat_FPS", "number"), "value": 5}, blocking=True)
    v = cam.config["Simplify.Encode"][0]["ExtraFormat"]["Video"]
    assert v["Compression"] == "H.264" and v["FPS"] == 5
    assert cam.config["Simplify.Encode"][0]["MainFormat"]["Video"]["FPS"] == 12  # untouched
    assert hass.states.get(eid(hass, "ExtraFormat_FPS", "number")).state == "5"

    await hass.services.async_call("switch", "turn_off",
        {"entity_id": eid(hass, "osd_time", "switch")}, blocking=True)
    t = cam.config["AVEnc.VideoWidget"][0]["TimeTitleAttribute"]
    assert t["EncodeBlend"] is False and t["PreviewBlend"] is False
    assert cam.config["AVEnc.VideoWidget"][0]["ChannelTitleAttribute"]["EncodeBlend"] is True

    await hass.services.async_call("switch", "turn_off", {"entity_id": eid(hass, "nat", "switch")}, blocking=True)
    assert cam.config["NetWork.Nat"]["NatEnable"] is False

    await hass.services.async_call("text", "set_value",
        {"entity_id": eid(hass, "ntp_server", "text"), "value": "192.168.1.254"}, blocking=True)
    n = cam.config["NetWork.NetNTP"]
    assert n["Server"]["Name"] == "192.168.1.254"
    assert n["NtpServerList"] == [{"Port": 123, "Server": "192.168.1.254"}]

    await hass.services.async_call("button", "press", {"entity_id": eid(hass, "sync_time", "button")}, blocking=True)
    assert cam.time is not None
    await hass.services.async_call("button", "press", {"entity_id": eid(hass, "reboot", "button")}, blocking=True)
    await asyncio.sleep(0.1)
    assert cam.rebooted


async def test_services(hass: HomeAssistant, cam):
    entry = await setup(hass, cam)
    r = await hass.services.async_call(DOMAIN, "get_config",
        {"config_entry_id": entry.entry_id, "name": "NetWork.Nat"}, blocking=True, return_response=True)
    assert r["value"]["Addr"] == "secu100.net"
    r = await hass.services.async_call(DOMAIN, "get_config",
        {"config_entry_id": entry.entry_id, "name": "EncodeCapability", "kind": "ability"},
        blocking=True, return_response=True)
    assert "EncodeInfo" in r["value"]
    nat = dict(cam.config["NetWork.Nat"], NatEnable=False)
    r = await hass.services.async_call(DOMAIN, "set_config",
        {"config_entry_id": entry.entry_id, "name": "NetWork.Nat", "data": nat}, blocking=True, return_response=True)
    assert r["ret"] == 100 and cam.config["NetWork.Nat"]["NatEnable"] is False
    with pytest.raises(Exception, match="607"):
        await hass.services.async_call(DOMAIN, "get_config",
            {"config_entry_id": entry.entry_id, "name": "Nope"}, blocking=True, return_response=True)


async def test_missing_sections_and_password(hass: HomeAssistant):
    cam = await FakeCamera(password_hash=sofia_hash("s3cret"), missing=["NetWork.Nat"]).start()
    try:
        await setup(hass, cam, password="s3cret")
        assert eid(hass, "nat", "switch") is None
        assert eid(hass, "osd_time", "switch") is not None
    finally:
        await cam.stop()


async def test_unreachable_retries(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="x",
        data={"host": "127.0.0.1", "port": 1, "username": "admin", "password": ""})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_full_model_picture_network(hass: HomeAssistant, cam):
    await setup(hass, cam)
    reg = er.async_get(hass)
    assert hass.states.get(eid(hass, "day_night", "select")).state == "Auto"
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid(hass, "flip", "switch")}, blocking=True)
    assert cam.config["Camera.Param.[0]"]["PictureFlip"] == "0x00000001"
    await hass.services.async_call("select", "select_option",
        {"entity_id": eid(hass, "day_night", "select"), "option": "Colour"}, blocking=True)
    assert cam.config["Camera.Param.[0]"]["DayNightColor"] == "0x00000001"
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid(hass, "wdr", "switch")}, blocking=True)
    assert cam.config["Camera.ParamEx.[0]"]["BroadTrends"]["AutoGain"] == 1
    await hass.services.async_call("number", "set_value",
        {"entity_id": eid(hass, "brightness", "number"), "value": 60}, blocking=True)
    assert cam.config["AVEnc.VideoColor.[0]"][0]["VideoColorParam"]["Brightness"] == 60
    assert cam.config["AVEnc.VideoColor.[0]"][1]["VideoColorParam"]["Brightness"] == 50
    assert reg.async_get(eid(hass, "hue", "number")).disabled_by is not None

    await hass.services.async_call("text", "set_value",
        {"entity_id": eid(hass, "camera_name", "text"), "value": "Front drive"}, blocking=True)
    assert cam.titles == ["Front drive"]
    await hass.services.async_call("select", "select_option",
        {"entity_id": eid(hass, "reboot_day", "select"), "option": "Never"}, blocking=True)
    assert cam.config["General.AutoMaintain"]["AutoRebootDay"] == "Never"

    assert hass.states.get(eid(hass, "ip", "sensor")).state == "192.168.6.175"
    assert hass.states.get(eid(hass, "gateway", "sensor")).state == "192.168.1.1"
    assert hass.states.get(eid(hass, "dhcp", "sensor")).state == "On"

    # IP allow list must never lock Home Assistant out
    sw = eid(hass, "ipfilter", "switch")
    with pytest.raises(Exception, match="allow list first"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": sw}, blocking=True)
    assert cam.config["NetWork.NetIPFilter"]["Enable"] is False
    txt = eid(hass, "ipfilter_trusted", "text")
    await hass.services.async_call("text", "set_value",
        {"entity_id": txt, "value": "127.0.0.1, 192.168.1.10"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": sw}, blocking=True)
    f = cam.config["NetWork.NetIPFilter"]
    assert f["Enable"] is True and len(f["Trusted"]) == 4 and f["Trusted"][0] == "0x0100007F"
    assert hass.states.get(txt).state == "127.0.0.1, 192.168.1.10"
    with pytest.raises(Exception, match="must keep Home Assistant"):
        await hass.services.async_call("text", "set_value",
            {"entity_id": txt, "value": "192.168.1.10"}, blocking=True)


async def test_two_channel_sparse_model(hass: HomeAssistant):
    cam = await FakeCamera(model="sparse2").start()
    try:
        await setup(hass, cam)
        assert eid(hass, "nat", "switch") is None
        assert eid(hass, "camera_name", "text") is None
        assert eid(hass, "ip", "sensor") is None
        assert eid(hass, "flip", "switch") is not None
        ch1 = eid(hass, "ch1_brightness", "number")
        assert hass.states.get(ch1).name.endswith("Channel 2 brightness")
        dn = hass.states.get(eid(hass, "day_night", "select"))
        assert dn.state == "0x00000005" and "0x00000005" in dn.attributes["options"]
        await hass.services.async_call("number", "set_value", {"entity_id": ch1, "value": 70}, blocking=True)
        assert cam.config["AVEnc.VideoColor.[1]"][0]["VideoColorParam"]["Brightness"] == 70
        assert cam.config["AVEnc.VideoColor.[0]"][0]["VideoColorParam"]["Brightness"] == 50
        await hass.services.async_call("number", "set_value",
            {"entity_id": eid(hass, "ch1_MainFormat_FPS", "number"), "value": 20}, blocking=True)
        enc = cam.config["Simplify.Encode"]
        assert enc[1]["MainFormat"]["Video"]["FPS"] == 20 and enc[0]["MainFormat"]["Video"]["FPS"] == 12
    finally:
        await cam.stop()


async def test_basic_model_has_no_picture_entities(hass: HomeAssistant):
    cam = await FakeCamera(model="basic").start()
    try:
        await setup(hass, cam)
        assert eid(hass, "flip", "switch") is None
        assert eid(hass, "brightness", "number") is None
        assert eid(hass, "osd_time", "switch") is not None
    finally:
        await cam.stop()


async def test_diagnostics(hass: HomeAssistant, cam):
    from custom_components.xmeye_config.diagnostics import async_get_config_entry_diagnostics
    entry = await setup(hass, cam, password="")
    d = await async_get_config_entry_diagnostics(hass, entry)
    assert "param" in d["supported_sections"]
    assert d["system_info"]["SerialNo"] == "**REDACTED**"
    assert d["entry"]["password"] in ("", "**REDACTED**")  # HA leaves empty values as-is
    assert d["extra_sections"]["Camera"]["Param"][0]["AeSensitivity"] == 5
    assert d["abilities"]["SystemFunction"].startswith("unavailable")
