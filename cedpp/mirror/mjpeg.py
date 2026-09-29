"""Minimal MJPEG (multipart/x-mixed-replace) reader for the Supernote mirror."""
from __future__ import annotations

import urllib.request
from typing import BinaryIO, Iterator
from urllib.parse import urlparse

SOI = b"\xff\xd8"   # JPEG start-of-image
EOI = b"\xff\xd9"   # JPEG end-of-image
MAX_BUFFER = 8 * 1024 * 1024


def normalize_address(text: str, port: int = 8080, path: str = "/screencast.mjpeg") -> str:
    """Accept '192.168.1.42', '192.168.1.42:8080' or a full URL; return the stream URL."""
    text = text.strip()
    if not text:
        raise ValueError("Enter the address shown on your Supernote.")
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if not parsed.hostname:
        raise ValueError(f"'{text}' doesn't look like an address.")
    netloc = parsed.hostname + f":{parsed.port or port}"
    return f"{parsed.scheme or 'http'}://{netloc}{parsed.path if parsed.path not in ('', '/') else path}"


def iter_jpegs(stream: BinaryIO, chunk_size: int = 16384) -> Iterator[bytes]:
    """Yield complete JPEG images from a multipart byte stream.

    Scans for JPEG start/end markers rather than trusting part headers, which
    differ between firmware versions.
    """
    read = getattr(stream, "read1", stream.read)
    buf = b""
    while True:
        chunk = read(chunk_size)
        if not chunk:
            return
        buf += chunk
        while True:
            start = buf.find(SOI)
            if start < 0:
                buf = buf[-1:]
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                buf = buf[start:]
                if len(buf) > MAX_BUFFER:  # corrupt stream - resync
                    buf = b""
                break
            yield buf[start:end + 2]
            buf = buf[end + 2:]


def open_stream(url: str, timeout: float) -> BinaryIO:
    request = urllib.request.Request(url, headers={"User-Agent": "SuperNote-CedPP/0.1"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - LAN URL from user
