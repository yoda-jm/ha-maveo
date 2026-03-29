"""Maveo guest QR code camera entities — one per active guest key."""
from __future__ import annotations

import io
import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import GuestUser, MaveoClient
from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator
from .guest_coordinator import MaveoGuestCoordinator

_LOGGER = logging.getLogger(__name__)


def _generate_qr_jpeg(url: str) -> bytes:
    """Render a URL as a QR code JPEG (blocking — run in executor)."""
    import qrcode
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    edata = hass.data[DOMAIN][entry.entry_id]

    for device_id, guest_coord in edata["guest_coordinators"].items():
        device = edata["devices"][device_id]
        device_coord = edata["coordinators"][device_id]
        client = edata["client"]
        _setup_guest_camera_tracking(
            hass, entry, guest_coord, device_coord, client, device_id, device, async_add_entities
        )


def _setup_guest_camera_tracking(
    hass: HomeAssistant,
    entry: ConfigEntry,
    guest_coord: MaveoGuestCoordinator,
    device_coord: MaveoDeviceCoordinator,
    client: MaveoClient,
    device_id: str,
    device,
    async_add_entities: AddEntitiesCallback,
) -> None:
    tracked: set[str] = set()

    @callback
    def _on_update() -> None:
        guests: list[GuestUser] = guest_coord.data or []
        new = [
            MaveoGuestQRCamera(guest_coord, device_coord, client, g.user_id, device_id, device)
            for g in guests
            if g.user_id not in tracked
        ]
        for e in new:
            tracked.add(e.user_id)
        if new:
            async_add_entities(new)

    entry.async_on_unload(guest_coord.async_add_listener(_on_update))
    _on_update()


class MaveoGuestQRCamera(CoordinatorEntity[MaveoGuestCoordinator], Camera):
    """Camera entity that displays a guest key's share link as a QR code."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:qrcode"
    _attr_frame_interval = 60  # only regenerate every 60 s at most

    def __init__(
        self,
        coordinator: MaveoGuestCoordinator,
        device_coordinator: MaveoDeviceCoordinator,
        client: MaveoClient,
        user_id: str,
        device_id: str,
        device,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self.user_id = user_id
        self._device_coord = device_coordinator
        self._client = client
        self._device_id = device_id
        self._device_name = device.name
        self._attr_unique_id = f"{device_id}_guest_{user_id}_qr"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

    def _get_guest(self) -> GuestUser | None:
        return next(
            (g for g in (self.coordinator.data or []) if g.user_id == self.user_id),
            None,
        )

    @property
    def available(self) -> bool:
        return self._get_guest() is not None

    @property
    def name(self) -> str:
        guest = self._get_guest()
        label = guest.nametag1 if (guest and guest.nametag1) else self.user_id[:8]
        return f"Guest QR: {label}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        guest = self._get_guest()
        if guest is None:
            return None
        if guest.ttl == "token expired" or (
            guest.ttl.isdigit() and int(guest.ttl) < __import__("time").time()
        ):
            return None  # expired — no QR to show

        device_data = self._device_coord.data or {}
        lat = device_data.get("gps_lat") or 0.0
        lng = device_data.get("gps_lng") or 0.0
        name = device_data.get("device_name") or self._device_name

        try:
            link = await self.hass.async_add_executor_job(
                lambda: self._client.generate_guest_link(
                    guest,
                    self._device_id,
                    name,
                    location_name=name,
                    latitude=lat,
                    longitude=lng,
                )
            )
            return await self.hass.async_add_executor_job(_generate_qr_jpeg, link)
        except Exception as err:
            _LOGGER.warning("QR generation failed for guest %s: %s", self.user_id, err)
            return None
