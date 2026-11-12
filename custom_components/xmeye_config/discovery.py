"""Finding Xiongmai cameras on the network.

Two methods:
- broadcast: the cameras' own search protocol (UDP 34569, msg 1530/1531). Fast
  and returns MAC/hostname, but only reaches the network Home Assistant is on.
- sweep: try TCP 34567 on every address in a subnet and confirm the device
  answers DVRIP. Works across VLANs as long as routing/firewall allow it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import struct
from dataclasses import dataclass

from .catalog import _hex_ip
from .dvrip import HEADER, sofia_hash

_LOGGER = logging.getLogger(__name__)

SEARCH_PORT = 34569
SEARCH_REQ = 1530
SEARCH_REPLY = 1531
MAX_SWEEP_HOSTS = 1024


@dataclass(frozen=True)
class FoundCamera:
    host: str
    port: int = 34567
    mac: str | None = None
    name: str | None = None
    method: str = "broadcast"


class _SearchProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, FoundCamera] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < HEADER.size:
            return
        *_, msg, length = HEADER.unpack(data[:HEADER.size])
        if msg != SEARCH_REPLY or length <= 0:
            return
        try:
            body = json.loads(data[HEADER.size:HEADER.size + length].replace(b"\x00", b""))
            net = body["NetWork.NetCommon"]
            host = _hex_ip(net["HostIP"])
        except (ValueError, KeyError, TypeError):
            return
        self.found[host] = FoundCamera(
            host=host, port=int(net.get("TCPPort") or 34567), mac=net.get("MAC"),
            name=net.get("HostName"), method="broadcast")


async def broadcast_search(timeout: float = 3.0, target: str = "255.255.255.255",
                           port: int = SEARCH_PORT, listen_port: int | None = None
                           ) -> list[FoundCamera]:
    """Ask every camera on the local network to identify itself."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        # Cameras reply to the search port, so we must listen on it.
        sock.bind(("", port if listen_port is None else listen_port))
    except OSError as err:
        _LOGGER.debug("Cannot listen on UDP %s for camera search: %s", port, err)
        sock.close()
        return []
    sock.setblocking(False)
    transport, proto = await loop.create_datagram_endpoint(_SearchProtocol, sock=sock)
    try:
        packet = struct.pack("<BBHIIHHI", 255, 0, 0, 0, 0, 0, SEARCH_REQ, 0)
        for _ in range(2):  # UDP: send twice in case one is dropped
            transport.sendto(packet, (target, port))
            await asyncio.sleep(timeout / 2)
    finally:
        transport.close()
    return sorted(proto.found.values(), key=lambda c: ipaddress.IPv4Address(c.host))


async def _probe(host: str, port: int, timeout: float) -> bool:
    """True if host:port answers a DVRIP login (even with a refusal)."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    try:
        body = json.dumps({"EncryptType": "MD5", "LoginType": "DVRIP-Web",
                           "PassWord": sofia_hash(""), "UserName": "admin"}).encode()
        writer.write(HEADER.pack(255, 0, 0, 0, 1000, len(body) + 2) + body + b"\x0a\x00")
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(HEADER.size), timeout)
        return head[0] == 255  # any DVRIP reply, accepted or refused
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        return False
    finally:
        writer.close()


async def sweep_subnet(subnet: str, port: int = 34567, timeout: float = 1.5,
                       concurrency: int = 64) -> list[FoundCamera]:
    """Probe every address in a subnet (e.g. 192.168.6.0/24) for DVRIP."""
    net = ipaddress.IPv4Network(subnet, strict=False)
    if net.num_addresses > MAX_SWEEP_HOSTS:
        raise ValueError(f"{subnet} is too large to sweep (max {MAX_SWEEP_HOSTS} addresses)")
    hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    sem = asyncio.Semaphore(concurrency)

    async def check(h: str) -> FoundCamera | None:
        async with sem:
            return FoundCamera(host=h, port=port, method="sweep") if await _probe(h, port, timeout) else None

    results = await asyncio.gather(*(check(h) for h in hosts))
    return [r for r in results if r]
