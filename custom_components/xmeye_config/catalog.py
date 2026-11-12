"""Declarative catalogue of camera settings.

Every entity comes from a Field here. A Field is only created for a camera
(and channel) when the camera actually returns a value of the right type at
that path, so cameras with different firmware get different entity sets and
new settings only need a line in FIELDS.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Any, Literal

ChannelMode = Literal["none", "list", "indexed"]


@dataclass(frozen=True)
class Section:
    """A config section. name may contain {ch} for indexed sections.

    none:    one value for the whole device
    list:    one read returns a list with an item per channel
    indexed: read/write "Name.[n]" separately for each channel
    """

    name: str
    channels: ChannelMode = "none"

    def wire_name(self, ch: int) -> str:
        return self.name.format(ch=ch) if self.channels == "indexed" else self.name


SECTIONS: dict[str, Section] = {
    "encode": Section("Simplify.Encode", "list"),
    "widget": Section("AVEnc.VideoWidget", "list"),
    "color": Section("AVEnc.VideoColor.[{ch}]", "indexed"),
    "param": Section("Camera.Param.[{ch}]", "indexed"),
    "paramex": Section("Camera.ParamEx.[{ch}]", "indexed"),
    "clearfog": Section("Camera.ClearFog.[{ch}]", "indexed"),
    "motion": Section("Detect.MotionDetect.[{ch}]", "indexed"),
    "blind": Section("Detect.BlindDetect.[{ch}]", "indexed"),
    "nat": Section("NetWork.Nat"),
    "ntp": Section("NetWork.NetNTP"),
    "netcommon": Section("NetWork.NetCommon"),
    "dhcp": Section("NetWork.NetDHCP"),
    "dns": Section("NetWork.NetDNS"),
    "upnp": Section("NetWork.Upnp"),
    "mobile": Section("NetWork.NetMobile"),
    "ipfilter": Section("NetWork.NetIPFilter"),
    "location": Section("General.Location"),
    "rtsp": Section("NetWork.RTSP"),
    "maintain": Section("General.AutoMaintain"),
}

# Sections only read for the diagnostics download, to help add new fields.
EXTRA_DIAGNOSTIC_SECTIONS = [
    "Camera", "General.General", "fVideo.OSDInfo", "fVideo.Volume",
    "fVideo.AudioInFormat", "NetWork.ChnStatus", "NetWork.DigTimeSyn",
    "NetWork.NetDDNS", "NetWork.NetEmail", "NetWork.NetFTP",
    "NetWork.OnvifPwdCheckout", "Storage.Snapshot", "Uart.PTZ", "Alarm.LocalAlarm",
    "Detect.HumanDetection", "AVEnc.SmartH264V2.[0]", "Camera.WhiteLight",
]
DIAGNOSTIC_ABILITIES = ["SystemFunction", "EncodeCapability", "Camera", "MultiLanguage"]


# ---- value converters ------------------------------------------------------

Kind = Literal["bool", "intbool", "hexbool", "int", "enum", "hexenum", "str", "ip"]


def _hex_ip(value: str) -> str:
    return socket.inet_ntoa(struct.pack("<I", int(value, 16)))


def ip_to_hex(ip: str) -> str:
    return "0x%08X" % struct.unpack("<I", socket.inet_aton(ip))[0]


def kind_ok(kind: Kind, raw: Any) -> bool:
    if raw is None:
        return False
    if kind == "bool":
        return isinstance(raw, bool)
    if kind in ("intbool", "int"):
        return isinstance(raw, int) and not isinstance(raw, bool)
    if kind in ("hexbool", "hexenum", "ip"):
        return isinstance(raw, str) and raw.lower().startswith("0x")
    return isinstance(raw, str)


def to_ha(kind: Kind, raw: Any, options: dict[str, Any] | None = None) -> Any:
    if kind == "intbool":
        return bool(raw)
    if kind == "hexbool":
        return int(raw, 16) != 0
    if kind == "ip":
        return _hex_ip(raw)
    if kind in ("enum", "hexenum") and options:
        norm = int(raw, 16) if kind == "hexenum" else raw
        for label, value in options.items():
            if value == norm:
                return label
        return str(raw)  # unknown value: shown as-is
    return raw


def from_ha(kind: Kind, value: Any, options: dict[str, Any] | None = None) -> Any:
    if kind == "intbool":
        return 1 if value else 0
    if kind == "hexbool":
        return "0x%08X" % (1 if value else 0)
    if kind == "int":
        return int(value)
    if kind in ("enum", "hexenum") and options and value in options:
        v = options[value]
        return "0x%08X" % v if kind == "hexenum" else v
    return value


# ---- the catalogue ---------------------------------------------------------

Platform = Literal["switch", "number", "select", "text", "sensor"]


@dataclass(frozen=True)
class Field:
    key: str                       # unique-id suffix
    platform: Platform
    section: str
    path: tuple[Any, ...]          # inside the channel's item
    name: str
    kind: Kind = "int"
    mirror: tuple[tuple[Any, ...], ...] = ()   # extra paths written with the same value
    options: dict[str, Any] | None = None      # select label -> raw
    min: float = 0
    max: float = 100
    step: float = 1
    unit: str | None = None
    enabled: bool = True           # enabled by default in the entity registry
    diagnostic: bool = False
    icon: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _stream_fields() -> list[Field]:
    out: list[Field] = []
    for stream, label in (("MainFormat", "Main stream"), ("ExtraFormat", "Substream")):
        v = (stream, "Video")
        out += [
            Field(f"{stream}_Resolution", "select", "encode", (*v, "Resolution"),
                  f"{label} resolution", "str", extra={"resolution": stream}),
            Field(f"{stream}_Compression", "select", "encode", (*v, "Compression"),
                  f"{label} codec", "enum", options={"H.264": "H.264", "H.265": "H.265"}),
            Field(f"{stream}_BitRateControl", "select", "encode", (*v, "BitRateControl"),
                  f"{label} bitrate mode", "enum", options={"CBR": "CBR", "VBR": "VBR"}),
            Field(f"{stream}_FPS", "number", "encode", (*v, "FPS"), f"{label} frame rate",
                  min=1, max=0, unit="fps", extra={"max_fps": True}),
            Field(f"{stream}_BitRate", "number", "encode", (*v, "BitRate"), f"{label} bitrate",
                  min=32, max=16384, step=32, unit="kbit/s"),
            Field(f"{stream}_GOP", "number", "encode", (*v, "GOP"),
                  f"{label} keyframe interval", min=1, max=12, unit="s"),
            Field(f"{stream}_Quality", "number", "encode", (*v, "Quality"),
                  f"{label} quality", min=1, max=6),
            Field(f"{stream}_audio", "switch", "encode", (stream, "AudioEnable"),
                  f"{label} audio", "bool"),
        ]
    out.append(Field("sub_video", "switch", "encode", ("ExtraFormat", "VideoEnable"),
                     "Substream enabled", "bool"))
    return out


DAY_NIGHT = {"Auto": 0, "Colour": 1, "Black & white": 2}
REBOOT_DAYS = {d: d for d in ("Never", "Everyday", "Sunday", "Monday", "Tuesday",
                              "Wednesday", "Thursday", "Friday", "Saturday")}

FIELDS: list[Field] = [
    *_stream_fields(),
    # overlays
    Field("osd_time", "switch", "widget", ("TimeTitleAttribute", "EncodeBlend"),
          "Timestamp overlay", "bool", mirror=(("TimeTitleAttribute", "PreviewBlend"),)),
    Field("osd_title", "switch", "widget", ("ChannelTitleAttribute", "EncodeBlend"),
          "Camera name overlay", "bool", mirror=(("ChannelTitleAttribute", "PreviewBlend"),)),
    # picture: colour
    Field("brightness", "number", "color", (0, "VideoColorParam", "Brightness"), "Brightness"),
    Field("contrast", "number", "color", (0, "VideoColorParam", "Contrast"), "Contrast"),
    Field("saturation", "number", "color", (0, "VideoColorParam", "Saturation"), "Saturation"),
    Field("hue", "number", "color", (0, "VideoColorParam", "Hue"), "Hue", enabled=False),
    # picture: sensor / ISP
    Field("flip", "switch", "param", ("PictureFlip",), "Flip image", "hexbool"),
    Field("mirror", "switch", "param", ("PictureMirror",), "Mirror image", "hexbool"),
    Field("day_night", "select", "param", ("DayNightColor",), "Day/night mode", "hexenum",
          options=DAY_NIGHT),
    Field("anti_flicker", "switch", "param", ("RejectFlicker",), "Anti-flicker", "hexbool"),
    Field("blc", "switch", "param", ("BLCMode",), "Backlight compensation", "hexbool"),
    Field("ae_sensitivity", "number", "param", ("AeSensitivity",), "Exposure sensitivity",
          min=1, max=10),
    Field("elec_level", "number", "param", ("ElecLevel",), "Exposure target level"),
    Field("day_nr", "number", "param", ("Day_nfLevel",), "Day noise reduction", min=0, max=5),
    Field("night_nr", "number", "param", ("Night_nfLevel",), "Night noise reduction",
          min=0, max=5),
    Field("dnc_threshold", "number", "param", ("DncThr",), "Day/night switch threshold",
          enabled=False),
    Field("ircut_swap", "switch", "param", ("IrcutSwap",), "Swap IR-cut filter", "intbool",
          enabled=False),
    Field("wdr", "switch", "paramex", ("BroadTrends", "AutoGain"), "Wide dynamic range",
          "intbool"),
    Field("wdr_level", "number", "paramex", ("BroadTrends", "Gain"), "WDR level"),
    Field("prevent_overexposure", "switch", "paramex", ("PreventOverExpo",),
          "Prevent overexposure", "intbool"),
    Field("defog", "switch", "clearfog", ("enable",), "Defog", "intbool"),
    Field("defog_level", "number", "clearfog", ("level",), "Defog level"),
    # detection
    Field("motion", "switch", "motion", ("Enable",), "Camera motion detection", "bool"),
    Field("motion_level", "number", "motion", ("Level",), "Motion sensitivity", min=1, max=6),
    Field("blind", "switch", "blind", ("Enable",), "Tamper detection", "bool"),
    Field("blind_level", "number", "blind", ("Level",), "Tamper sensitivity", min=1, max=6),
    # network
    Field("nat", "switch", "nat", ("NatEnable",), "Cloud connection (XMEye)", "bool"),
    Field("upnp", "switch", "upnp", ("Enable",), "UPnP port forwarding", "bool"),
    Field("mobile", "switch", "mobile", ("Enable",), "Mobile monitoring service", "bool",
          enabled=False),
    Field("ntp_enable", "switch", "ntp", ("Enable",), "NTP time sync", "bool"),
    Field("hostname", "text", "netcommon", ("HostName",), "Hostname", "str"),
    Field("ip", "sensor", "netcommon", ("HostIP",), "IP address", "ip", diagnostic=True),
    Field("netmask", "sensor", "netcommon", ("Submask",), "Subnet mask", "ip",
          diagnostic=True, enabled=False),
    Field("gateway", "sensor", "netcommon", ("GateWay",), "Gateway", "ip", diagnostic=True),
    Field("mac", "sensor", "netcommon", ("MAC",), "MAC address", "str", diagnostic=True),
    Field("http_port", "sensor", "netcommon", ("HttpPort",), "HTTP port",
          diagnostic=True, enabled=False),
    Field("tcp_port", "sensor", "netcommon", ("TCPPort",), "DVRIP port",
          diagnostic=True, enabled=False),
    Field("dhcp", "sensor", "dhcp", (0, "Enable"), "DHCP", "bool", diagnostic=True),
    Field("dns1", "sensor", "dns", ("Address",), "DNS server", "ip", diagnostic=True,
          enabled=False),
    # maintenance
    Field("reboot_day", "select", "maintain", ("AutoRebootDay",), "Scheduled reboot",
          "enum", options=REBOOT_DAYS),
    Field("reboot_hour", "number", "maintain", ("AutoRebootHour",), "Scheduled reboot hour",
          min=0, max=23, unit="h"),
]
