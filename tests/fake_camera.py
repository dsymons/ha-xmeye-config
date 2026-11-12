"""Fake Xiongmai camera speaking DVRIP, seeded with real config dumps."""
import asyncio, copy, json, struct

HEADER = struct.Struct("<BB2xII2xHI")
PASSWORD_HASH = "tlJwpbo6"  # sofia_hash("")

def V(res, fps): return {"BitRate": 2560 if res == "3M" else 1280, "BitRateControl": "VBR",
    "Compression": "H.265", "FPS": fps, "GOP": 2, "Quality": 3, "Resolution": res, "VirtualGOP": 1}

def attr(on, pos): return {"BackColor": "0x40000000", "EncodeBlend": on, "FrontColor": "0xF0FFFFFF",
    "PreviewBlend": on, "RelativePos": pos}

CONFIG = {
 "Simplify.Encode": [{"ExtraFormat": {"AudioEnable": True, "Video": V("D1", 12), "VideoEnable": True},
                      "MainFormat": {"AudioEnable": True, "Video": V("3M", 12), "VideoEnable": True}}],
 "AVEnc.VideoWidget": [{"ChannelTitle": {"Name": "Robot", "SerialNo": "00000000"},
    "ChannelTitleAttribute": attr(True, [160, 7552, 255, 24]), "Covers": [], "CoversNum": 0,
    "TimeTitleAttribute": attr(True, [7166, 512, 255, 24])}],
 "NetWork.Nat": {"Addr": "secu100.net", "NatEnable": True, "Port": 8765, "XMeyeMTU": 1280},
 "NetWork.NetNTP": {"Enable": True, "NtpServerList": [{"Port": 123, "Server": "time.windows.com"},
    {"Port": 123, "Server": "0.pool.ntp.org"}], "Server": {"Address": "0x00000000", "Anonymity": False,
    "Name": "time.windows.com", "Password": "", "Port": 123, "UserName": ""}, "TimeZone": 14, "UpdatePeriod": 10},
 "General.Location": {"VideoFormat": "PAL", "Language": "English"},
}
PARAM = {"AeSensitivity": 5, "ApertureMode": "0x00000000", "BLCMode": "0x00000000",
    "DayNightColor": "0x00000000", "Day_nfLevel": 3, "DncThr": 30, "ElecLevel": 50,
    "EsShutter": "0x00000002", "ExposureParam": {"LeastTime": "0x00000100", "Level": 0,
    "MostTime": "0x00010000"}, "GainParam": {"AutoGain": 1, "Gain": 50}, "IRCUTMode": 0,
    "IrcutSwap": 0, "Night_nfLevel": 3, "PictureFlip": "0x00000000",
    "PictureMirror": "0x00000000", "RejectFlicker": "0x00000000", "WhiteBalance": "0x00000000"}
PARAMEX = {"AutomaticAdjustment": 3, "BroadTrends": {"AutoGain": 0, "Gain": 50},
    "CorridorMode": 0, "ExposureTime": "0x100", "LightRestrainLevel": 16, "LowLuxMode": 0,
    "PreventOverExpo": 0, "SoftPhotosensitivecontrol": 0, "Style": "type1"}
COLOR = [{"Enable": True, "TimeSection": "0 00:00:00-24:00:00", "VideoColorParam": {
    "Acutance": 3848, "Brightness": 50, "Contrast": 50, "Gain": 0, "Hue": 50,
    "Saturation": 50, "Whitebalance": 128}}] * 2
FULL = dict(CONFIG, **{
 "Camera.Param.[0]": PARAM, "Camera.ParamEx.[0]": PARAMEX,
 "Camera.ClearFog.[0]": {"enable": 0, "level": 50},
 "AVEnc.VideoColor.[0]": COLOR,
 "Detect.MotionDetect.[0]": {"Enable": True, "Level": 3, "Region": ["0xFFFFFF"]},
 "Detect.BlindDetect.[0]": {"Enable": False, "Level": 3},
 "NetWork.NetCommon": {"GateWay": "0x0101A8C0", "HostIP": "0xAF06A8C0", "HostName": "LocalHost",
    "HttpPort": 80, "MAC": "00:12:34:56:78:9a", "Submask": "0x00FFFFFF", "TCPPort": 34567},
 "NetWork.NetDHCP": [{"Enable": True, "Interface": "eth0"}],
 "NetWork.NetDNS": {"Address": "0x0101A8C0", "SpareAddress": "0x08080808"},
 "NetWork.Upnp": {"Enable": True, "HTTPPort": 80, "MediaPort": 34567, "MobilePort": 34599, "State": False},
 "NetWork.NetMobile": {"Enable": True},
 "NetWork.NetIPFilter": {"Banned": ["0x00000000"] * 4, "Enable": False, "Trusted": ["0x00000000"] * 4},
 "General.AutoMaintain": {"AutoDeleteFilesDays": 0, "AutoRebootDay": "Tuesday", "AutoRebootHour": 3},
 "Camera": {"Param": [PARAM]},
})
SPARSE2 = {  # two-channel device with few sections and an odd day/night value
 "Simplify.Encode": CONFIG["Simplify.Encode"] * 2,
 "AVEnc.VideoWidget": CONFIG["AVEnc.VideoWidget"] * 2,
 "AVEnc.VideoColor.[0]": COLOR, "AVEnc.VideoColor.[1]": COLOR,
 "Camera.Param.[0]": dict(PARAM, DayNightColor="0x00000005"),
 "Camera.Param.[1]": PARAM,
}
# Bits: D1(0), VGA(5), 720P(11), 1080P(14), 3M(18)
ABILITY = {"EncodeCapability": {"EncodeInfo": [
    {"StreamType": "MainStream", "ResolutionMask": hex((1<<11)|(1<<14)|(1<<18))},
    {"StreamType": "ExtraStream", "ResolutionMask": hex(1|(1<<5))}]}}
SYSINFO = {"HardWare": "IPC_GK7205V300_S38", "SerialNo": "abc123def456", "SoftWareVersion": "V5.00.R02"}

class FakeCamera:
    def __init__(self, password_hash=PASSWORD_HASH, missing=(), model="full"):
        self.config = copy.deepcopy({"full": FULL, "basic": CONFIG, "sparse2": SPARSE2}[model])
        self.channels = 2 if model == "sparse2" else 1
        self.titles = ["Robot"] if model == "full" else None
        for m in missing: self.config.pop(m)
        self.password_hash = password_hash
        self.log = []
        self.time = None
        self.rebooted = False

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close(); await self.server.wait_closed()

    async def handle(self, r, w):
        session = 0
        try:
            while True:
                head = await r.readexactly(20)
                _, _, sess, seq, msg, length = HEADER.unpack(head)
                body = json.loads((await r.readexactly(length))[:-2])
                name = body.get("Name")
                self.log.append((msg, name))
                if msg == 1000:
                    if body["PassWord"] != self.password_hash:
                        reply = {"Ret": 203, "SessionID": "0x00000000"}
                    else:
                        session = 0x1A; reply = {"Ret": 100, "SessionID": "0x0000001A",
                            "AliveInterval": 20, "DeviceType ": "IPC"}
                elif sess != session or not session:
                    reply = {"Ret": 105}
                elif msg == 1020:
                    reply = {"Ret": 100, "Name": name, name: dict(SYSINFO, VideoInChannel=self.channels)}
                elif msg == 1048:
                    reply = ({"Ret": 100, "Name": name, name: self.titles} if self.titles is not None
                             else {"Ret": 607})
                elif msg == 1046:
                    if self.titles is None: reply = {"Ret": 607}
                    else: self.titles = body[name]; reply = {"Ret": 100}
                elif msg == 1042:
                    reply = ({"Ret": 100, "Name": name, name: self.config[name]} if name in self.config
                             else {"Ret": 607, "Name": name})
                elif msg == 1360:
                    reply = ({"Ret": 100, "Name": name, name: ABILITY[name]} if name in ABILITY
                             else {"Ret": 607, "Name": name})
                elif msg == 1040:
                    if name not in self.config: reply = {"Ret": 607}
                    else:
                        self.config[name] = body[name]; reply = {"Ret": 100, "Name": name}
                elif msg == 1450 and name == "OPMachine":
                    self.rebooted = True; break
                elif msg == 1450 and name == "OPTimeSetting":
                    self.time = body[name]; reply = {"Ret": 100}
                else:
                    reply = {"Ret": 502}
                data = json.dumps(reply).encode() + b"\x0a\x00"
                w.write(HEADER.pack(255, 0, session, seq, msg, len(data)) + data)
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()
