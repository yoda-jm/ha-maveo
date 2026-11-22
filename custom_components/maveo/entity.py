"""Shared entity helpers for Maveo."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def maveo_device_info(device_id: str, name: str) -> DeviceInfo:
    """Device registry entry shared by all entities of one Maveo stick."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=name,
        manufacturer="Marantec",
        model="Maveo",
    )
