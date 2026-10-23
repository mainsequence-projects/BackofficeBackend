"""Losslessly recompress the complete PNG/APNG frame streams emitted by Pillow."""

import struct
import zlib


def optimize_png(path):
    original = path.read_bytes()
    assert original[:8] == b"\x89PNG\r\n\x1a\n"
    output, offset = bytearray(original[:8]), 8
    while offset < len(original):
        length = struct.unpack(">I", original[offset : offset + 4])[0]
        kind = original[offset + 4 : offset + 8]
        data = original[offset + 8 : offset + 8 + length]
        crc = original[offset + 8 + length : offset + 12 + length]
        assert struct.unpack(">I", crc)[0] == zlib.crc32(kind + data)
        offset += length + 12
        if kind in (b"IDAT", b"fdAT"):
            sequence = data[:4] if kind == b"fdAT" else b""
            compressed = data[len(sequence) :]
            try:
                raw = zlib.decompress(compressed)
            except zlib.error:
                # A stream split across multiple chunks is already valid; leave it unchanged.
                raw = None
            if raw is not None:
                choices = [compressed]
                for strategy in (
                    zlib.Z_DEFAULT_STRATEGY,
                    zlib.Z_FILTERED,
                    zlib.Z_RLE,
                    zlib.Z_FIXED,
                ):
                    encoder = zlib.compressobj(9, zlib.DEFLATED, 15, 9, strategy)
                    choices.append(encoder.compress(raw) + encoder.flush())
                data = sequence + min(choices, key=len)
        output.extend(
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )
    assert offset == len(original)
    if len(output) < len(original):
        path.write_bytes(output)
