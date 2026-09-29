"""Reader for the Supernote mirror's multipart/x-mixed-replace stream.

Firmware varies: parts are labelled image/jpeg but may actually be PNG
(observed on a real device: Ktor server, 1404x1872 grayscale PNG parts with
Content-Length). So we split on the multipart boundary, trust Content-Length
when present, and let the decoder sniff the real format from the bytes.
"""
from __future__ import annotations

import re
import socket
import urllib.request
from typing import BinaryIO, Iterator, Optional
from urllib.parse import urlparse

SOI = b"\xff\xd8"   # JPEG start-of-image
EOI = b"\xff\xd9"   # JPEG end-of-image
MAX_BUFFER = 16 * 1024 * 1024
MAX_HEADER = 16 * 1024


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


def boundary_from_content_type(content_type: Optional[str]) -> Optional[bytes]:
    if not content_type:
        return None
    match = re.search(r'boundary="?([^";]+)"?', content_type, re.IGNORECASE)
    return match.group(1).strip().encode() if match else None


class _Buffer:
    """Byte buffer over a stream with 'read until' helpers."""

    def __init__(self, stream: BinaryIO, chunk_size: int) -> None:
        self._read = getattr(stream, "read1", stream.read)
        self.chunk_size = chunk_size
        self.data = b""

    def fill(self) -> bool:
        chunk = self._read(self.chunk_size)
        if not chunk:
            return False
        self.data += chunk
        if len(self.data) > MAX_BUFFER:
            raise ValueError("Mirror stream frame is too large or corrupt.")
        return True

    def find(self, needle: bytes, limit: int = MAX_BUFFER) -> int:
        """Index of needle, reading more as needed; -1 at end of stream."""
        start = 0
        while True:
            i = self.data.find(needle, start)
            if i >= 0:
                return i
            start = max(0, len(self.data) - len(needle) + 1)
            if len(self.data) > limit or not self.fill():
                return -1

    def take(self, n: int) -> Optional[bytes]:
        while len(self.data) < n:
            if not self.fill():
                return None
        out, self.data = self.data[:n], self.data[n:]
        return out


def iter_parts(stream: BinaryIO, boundary: bytes, chunk_size: int = 65536) -> Iterator[bytes]:
    """Yield each part body of a multipart stream."""
    buf = _Buffer(stream, chunk_size)
    delim = b"--" + boundary
    while True:
        i = buf.find(delim)
        if i < 0:
            return
        buf.data = buf.data[i + len(delim):]
        j = buf.find(b"\r\n\r\n", limit=MAX_HEADER)
        if j < 0:
            return
        headers = buf.data[:j]
        buf.data = buf.data[j + 4:]
        if headers.startswith(b"--"):          # closing delimiter
            return
        length = None
        for line in headers.split(b"\r\n"):
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length" and value.strip().isdigit():
                length = int(value.strip())
        if length is not None:
            body = buf.take(length)
            if body is None:
                return
        else:
            k = buf.find(delim)
            if k < 0:
                return
            body = buf.data[:k].rstrip(b"\r\n")
            buf.data = buf.data[k:]
        if body:
            yield body


def iter_jpegs(stream: BinaryIO, chunk_size: int = 16384) -> Iterator[bytes]:
    """Fallback for streams without a boundary: split on JPEG start/end markers."""
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


def iter_images(stream: BinaryIO, content_type: Optional[str]) -> Iterator[bytes]:
    """Encoded image bytes (PNG or JPEG) from the mirror response."""
    boundary = boundary_from_content_type(content_type)
    if boundary:
        return iter_parts(stream, boundary)
    return iter_jpegs(stream)


def open_stream(url: str, connect_timeout: float, read_timeout: float = 20.0):
    """Fail fast if the tablet is unreachable, but allow slow first frames
    (the device sometimes takes several seconds to start streaming)."""
    parsed = urlparse(url)
    socket.create_connection((parsed.hostname, parsed.port or 80), timeout=connect_timeout).close()
    request = urllib.request.Request(url, headers={"User-Agent": "SuperNote-CedPP/0.1"})
    return urllib.request.urlopen(request, timeout=read_timeout)  # noqa: S310 - LAN URL from user
