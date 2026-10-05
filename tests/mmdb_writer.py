"""Minimal MaxMind DB (MMDB v2) writer for tests: synthetic IPv4 networks -> country records.

Produces a real .mmdb file read by the official `maxminddb` library, so GeoIP code is tested against the
actual file format without shipping any third-party database. Only uses documentation/test address ranges.
"""
from __future__ import annotations

import ipaddress
import struct
import time


def _ctrl(type_num: int, size: int) -> bytes:
    ext = b""
    if type_num > 7:
        ext = bytes([type_num - 7])
        type_num = 0
    if size < 29:
        return bytes([(type_num << 5) | size]) + ext
    if size < 285:
        return bytes([(type_num << 5) | 29]) + ext + bytes([size - 29])
    return bytes([(type_num << 5) | 30]) + ext + struct.pack(">H", size - 285)


def encode(value) -> bytes:
    if isinstance(value, str):
        raw = value.encode()
        return _ctrl(2, len(raw)) + raw
    if isinstance(value, dict):
        out = _ctrl(7, len(value))
        for k, v in value.items():
            out += encode(k) + encode(v)
        return out
    if isinstance(value, list):
        out = _ctrl(11, len(value))
        for v in value:
            out += encode(v)
        return out
    if isinstance(value, tuple) and value[0] in ("u16", "u32", "u64"):
        kind, num = value
        raw = num.to_bytes(8, "big").lstrip(b"\x00")
        return _ctrl({"u16": 5, "u32": 6, "u64": 9}[kind], len(raw)) + raw
    raise TypeError(value)


def build(networks: dict[str, tuple[str, str]], path) -> None:
    """networks: {"5.42.0.0/24": ("SA", "Saudi Arabia"), ...}"""
    root = [None, None]
    data = b""
    offsets = {}
    for cidr, (code, name) in networks.items():
        net = ipaddress.ip_network(cidr)
        rec = {"country": {"iso_code": code, "names": {"en": name}}}
        key = (code, name)
        if key not in offsets:
            offsets[key] = len(data)
            data += encode(rec)
        bits = format(int(net.network_address), "032b")[: net.prefixlen]
        node = root
        for i, b in enumerate(bits):
            idx = int(b)
            if i == len(bits) - 1:
                node[idx] = ("data", offsets[key])
            else:
                if not isinstance(node[idx], list):
                    node[idx] = [None, None]
                node = node[idx]
    order, queue = [], [root]
    while queue:
        n = queue.pop(0)
        order.append(n)
        queue.extend(c for c in n if isinstance(c, list))
    index = {id(n): i for i, n in enumerate(order)}
    count = len(order)

    def rec_value(r):
        if isinstance(r, list):
            return index[id(r)]
        if isinstance(r, tuple):
            return count + 16 + r[1]
        return count

    tree = b"".join(rec_value(n[0]).to_bytes(3, "big") + rec_value(n[1]).to_bytes(3, "big") for n in order)
    meta = encode({
        "binary_format_major_version": ("u16", 2), "binary_format_minor_version": ("u16", 0),
        "build_epoch": ("u64", int(time.time())), "database_type": "GeoLite2-Country",
        "description": {"en": "Synthetic test database"}, "ip_version": ("u16", 4), "languages": ["en"],
        "node_count": ("u32", count), "record_size": ("u16", 24),
    })
    with open(path, "wb") as fh:
        fh.write(tree + b"\x00" * 16 + data + b"\xab\xcd\xefMaxMind.com" + meta)


# Synthetic mapping of a few public ranges to example countries (documentation ranges count as internal).
TEST_NETWORKS = {
    "5.42.0.0/24": ("SA", "Saudi Arabia"),
    "14.96.0.0/24": ("IN", "India"),
    "23.0.0.0/24": ("US", "United States"),
    "31.145.0.0/24": ("TR", "Türkiye"),
}
