"""Digest the firmware stamps on workflow plans so the host can verify them."""

from __future__ import annotations

FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3


def fnv1a64(data: bytes) -> int:
    """Return the 64-bit FNV-1a digest of ``data``, matching the firmware's."""
    digest = FNV1A64_OFFSET
    for byte in data:
        digest ^= byte
        digest = (digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
    return digest
