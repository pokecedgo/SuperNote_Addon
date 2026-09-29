"""Find a Supernote mirror on the local network (port 8080, multipart stream)."""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional


def local_ipv4() -> Optional[str]:
    """This machine's LAN address (no packets are actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def probe(host: str, port: int = 8080, path: str = "/screencast.mjpeg",
          timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout * 2)
            sock.sendall(f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            head = sock.recv(1024).lower()
            return b"multipart" in head or b"image/jpeg" in head
    except OSError:
        return False


def scan(port: int = 8080, path: str = "/screencast.mjpeg") -> List[str]:
    """Probe every host on this machine's /24 subnet. Takes a few seconds."""
    me = local_ipv4()
    if not me:
        return []
    network = ipaddress.ip_network(f"{me}/24", strict=False)
    hosts = [str(h) for h in network.hosts() if str(h) != me]
    with ThreadPoolExecutor(max_workers=64) as pool:
        found = pool.map(lambda h: h if probe(h, port, path) else None, hosts)
    return [h for h in found if h]
