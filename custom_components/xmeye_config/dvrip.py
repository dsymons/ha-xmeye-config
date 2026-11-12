"""Minimal asyncio client for the Xiongmai DVRIP ("Sofia") protocol on port 34567.

Each operation opens a short session (connect, login, commands, close) so the
camera's limited session slots are never held open by Home Assistant.
Protocol details follow the OpenIPC python-dvr project (MIT licence).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from datetime import datetime
from typing import Any

HEADER = struct.Struct("<BB2xII2xHI")

LOGIN = 1000
KEEPALIVE = 1006
SYSINFO = 1020
CONFIG_SET = 1040
CONFIG_GET = 1042
ABILITY_GET = 1360
OP_MACHINE = 1450
OP_TIME_SETTING = 1450
OP_SNAP = 1560
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
CHANNEL_TITLE_SET = 1046
CHANNEL_TITLE_GET = 1048

OK_CODES = (100, 150, 515)
AUTH_CODES = (106, 203, 204, 205, 206, 207)

RET_MESSAGES = {
    101: "Unknown error",
    103: "Request not permitted",
    105: "User is not logged in",
    106: "Username or password is incorrect",
    107: "User does not have necessary permissions",
    117: "Message format error",
    150: "Operation successful, device restart required",
    203: "Password is incorrect",
    204: "User does not exist",
    205: "Login locked after too many failed attempts",
    206: "User is blacklisted",
    207: "Address is blacklisted",
    502: "Command is invalid",
    603: "System restart required",
    605: "Feature not supported",
    607: "Configuration does not exist",
    608: "Configuration parse error",
}


class DVRIPError(Exception):
    """Communication or protocol failure."""


class DVRIPAuthError(DVRIPError):
    """Login rejected. ret is the camera's code (203 wrong password, 205 IP locked...)."""

    def __init__(self, ret: int | None) -> None:
        self.ret = ret
        super().__init__(f"Login refused: {RET_MESSAGES.get(ret, 'unknown reason')} ({ret})")

    @property
    def locked(self) -> bool:
        return self.ret in (205, 206, 207)


class DVRIPCommandError(DVRIPError):
    """Camera answered with a non-OK return code."""

    def __init__(self, name: str, ret: int) -> None:
        self.ret = ret
        msg = RET_MESSAGES.get(ret, "Unknown return code")
        super().__init__(f"{name}: camera returned {ret} ({msg})")


def sofia_hash(password: str) -> str:
    """Xiongmai's password hash (MD5 folded into 8 base-62 characters)."""
    md5 = hashlib.md5(password.encode("utf-8")).digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(a + b) % 62] for a, b in zip(md5[::2], md5[1::2]))


def _decode(payload: bytes) -> dict[str, Any]:
    payload = payload.rstrip(b"\x00").rstrip(b"\n").rstrip(b"\x00")
    cleaned = bytes(b for b in payload if b >= 32 or b in (9, 10, 13))
    try:
        text = cleaned.decode("utf-8")
    except UnicodeDecodeError:
        text = cleaned.decode("latin1")
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError as err:
        raise DVRIPError(f"Malformed reply from camera: {err}") from err


class DVRIPSession:
    """One logged-in connection. Use via `async with DVRIPClient.session()`."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 timeout: float) -> None:
        self._reader = reader
        self._writer = writer
        self._timeout = timeout
        self._session = 0
        self._seq = 0

    @property
    def local_ip(self) -> str | None:
        """Our address as the camera sees it (used to avoid locking ourselves out)."""
        sock = self._writer.get_extra_info("sockname")
        return sock[0] if sock else None

    @property
    def session_hex(self) -> str:
        return "0x%08X" % self._session

    async def request(self, msg_id: int, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        packet = HEADER.pack(255, 0, self._session, self._seq, msg_id, len(data) + 2)
        self._writer.write(packet + data + b"\x0a\x00")
        self._seq += 1
        try:
            await asyncio.wait_for(self._writer.drain(), self._timeout)
            head = await asyncio.wait_for(self._reader.readexactly(HEADER.size), self._timeout)
            _, _, session, _, _, length = HEADER.unpack(head)
            payload = await asyncio.wait_for(self._reader.readexactly(length), self._timeout)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError) as err:
            raise DVRIPError(f"No reply from camera: {err!r}") from err
        if session:
            self._session = session
        return _decode(payload)

    async def login(self, username: str, password: str) -> dict[str, Any]:
        reply = await self.request(LOGIN, {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": sofia_hash(password),
            "UserName": username,
        })
        ret = reply.get("Ret")
        if ret not in OK_CODES:
            if ret in AUTH_CODES:
                raise DVRIPAuthError(ret)
            raise DVRIPCommandError("Login", ret)
        self._session = int(reply["SessionID"], 16)
        return reply

    async def _named(self, msg_id: int, name: str) -> Any:
        reply = await self.request(msg_id, {"Name": name, "SessionID": self.session_hex})
        ret = reply.get("Ret")
        if ret not in OK_CODES:
            raise DVRIPCommandError(name, ret)
        return reply.get(name)

    async def get_config(self, name: str) -> Any:
        return await self._named(CONFIG_GET, name)

    async def get_ability(self, name: str) -> Any:
        return await self._named(ABILITY_GET, name)

    async def get_system_info(self) -> dict[str, Any]:
        return await self._named(SYSINFO, "SystemInfo") or {}

    async def set_config(self, name: str, value: Any) -> int:
        reply = await self.request(CONFIG_SET, {
            "Name": name, "SessionID": self.session_hex, name: value,
        })
        ret = reply.get("Ret")
        if ret not in OK_CODES:
            raise DVRIPCommandError(name, ret)
        return ret

    async def get_channel_titles(self) -> list[str]:
        return await self._named(CHANNEL_TITLE_GET, "ChannelTitle") or []

    async def set_channel_titles(self, titles: list[str]) -> None:
        reply = await self.request(CHANNEL_TITLE_SET, {
            "Name": "ChannelTitle", "SessionID": self.session_hex, "ChannelTitle": titles,
        })
        if reply.get("Ret") not in OK_CODES:
            raise DVRIPCommandError("ChannelTitle", reply.get("Ret"))

    async def snapshot(self, channel: int = 0) -> bytes:
        """Ask the camera for a JPEG still (OPSNAP). Raises DVRIPError if unsupported."""
        body = json.dumps({"Name": "OPSNAP", "SessionID": self.session_hex,
                           "OPSNAP": {"Channel": channel}}).encode()
        self._writer.write(HEADER.pack(255, 0, self._session, self._seq, OP_SNAP, len(body) + 2)
                           + body + b"\x0a\x00")
        self._seq += 1
        buf = bytearray()
        expected: int | None = None
        try:
            await asyncio.wait_for(self._writer.drain(), self._timeout)
            while True:
                head = await asyncio.wait_for(self._reader.readexactly(HEADER.size), self._timeout)
                length = HEADER.unpack(head)[5]
                packet = await asyncio.wait_for(self._reader.readexactly(length), self._timeout)
                if not buf and expected is None:
                    if packet[:1] == b"{":
                        reply = _decode(packet)
                        raise DVRIPCommandError("OPSNAP", reply.get("Ret"))
                    if packet[:4] == b"\x00\x00\x01\xfe":   # media frame header + JPEG
                        expected = struct.unpack("<I", packet[12:16])[0]
                        packet = packet[16:]
                    elif packet[:2] != b"\xff\xd8":
                        raise DVRIPError("Unexpected snapshot data from camera")
                buf.extend(packet)
                if len(buf) > MAX_SNAPSHOT_BYTES:
                    raise DVRIPError("Snapshot too large")
                if expected is not None and len(buf) >= expected:
                    return bytes(buf[:expected])
                if expected is None and buf.endswith(b"\xff\xd9"):
                    return bytes(buf)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError) as err:
            raise DVRIPError(f"Snapshot failed: {err!r}") from err

    async def reboot(self) -> None:
        body = {"Name": "OPMachine", "SessionID": self.session_hex,
                "OPMachine": {"Action": "Reboot"}}
        packet_data = json.dumps(body).encode()
        self._writer.write(
            HEADER.pack(255, 0, self._session, self._seq, OP_MACHINE, len(packet_data) + 2)
            + packet_data + b"\x0a\x00")
        await self._writer.drain()  # camera usually drops the link without replying

    async def set_time(self, when: datetime) -> None:
        reply = await self.request(OP_TIME_SETTING, {
            "Name": "OPTimeSetting", "SessionID": self.session_hex,
            "OPTimeSetting": when.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if reply.get("Ret") not in OK_CODES:
            raise DVRIPCommandError("OPTimeSetting", reply.get("Ret"))


class _SessionContext:
    def __init__(self, client: "DVRIPClient") -> None:
        self._client = client
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> DVRIPSession:
        c = self._client
        await c.lock.acquire()
        try:
            try:
                reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(c.host, c.port), c.timeout)
            except (asyncio.TimeoutError, OSError) as err:
                raise DVRIPError(f"Cannot connect to {c.host}:{c.port}: {err!r}") from err
            session = DVRIPSession(reader, self._writer, c.timeout)
            await session.login(c.username, c.password)
            return session
        except BaseException:
            await self._close()
            c.lock.release()
            raise

    async def _close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), 2)
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
            self._writer = None

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self._close()
        finally:
            self._client.lock.release()


class DVRIPClient:
    """Connection settings plus a lock so only one session runs at a time."""

    def __init__(self, host: str, port: int = 34567, username: str = "admin",
                 password: str = "", timeout: float = 10) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.lock = asyncio.Lock()

    def session(self) -> _SessionContext:
        return _SessionContext(self)
