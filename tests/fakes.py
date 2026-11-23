"""Fake Maveo cloud services used at the network boundary.

- Cognito (user pool + identity pool) is a moto server on 127.0.0.1.
- The REST admin API and the stick's MQTT-over-WebSocket endpoint are served
  by one local aiohttp server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import boto3
from aiohttp import WSMsgType, web
from mypy_boto3_cognito_idp import CognitoIdentityProviderClient

from custom_components.maveo.api import iot

AWS_REGION = "eu-central-1"
EMAIL = "owner@example.com"
PASSWORD = "Correct-horse-1"
DEVICE_ID = "1001"
DEVICE_NAME = "Garage"


@dataclass(frozen=True)
class CognitoPool:
    endpoint_url: str
    user_pool_id: str
    client_id: str
    identity_pool_id: str

    def idp(self) -> CognitoIdentityProviderClient:
        """boto3 client for test setup against the moto server."""
        return boto3.client(
            "cognito-idp", region_name=AWS_REGION, endpoint_url=self.endpoint_url
        )

    def add_user(self, email: str, password: str = PASSWORD) -> None:
        idp = self.idp()
        idp.admin_create_user(
            UserPoolId=self.user_pool_id, Username=email, MessageAction="SUPPRESS"
        )
        idp.admin_set_user_password(
            UserPoolId=self.user_pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )


def create_cognito_pool(endpoint_url: str) -> CognitoPool:
    """Create a user pool, app client, user and identity pool on moto."""
    idp = boto3.client("cognito-idp", region_name=AWS_REGION, endpoint_url=endpoint_url)
    pool_id = idp.create_user_pool(PoolName="maveo")["UserPool"]["Id"]
    client_id = idp.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="maveo-app",
        ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )["UserPoolClient"]["ClientId"]
    identity = boto3.client(
        "cognito-identity", region_name=AWS_REGION, endpoint_url=endpoint_url
    )
    identity_pool_id = identity.create_identity_pool(
        IdentityPoolName="maveo",
        AllowUnauthenticatedIdentities=False,
        CognitoIdentityProviders=[
            {
                "ProviderName": f"cognito-idp.{AWS_REGION}.amazonaws.com/{pool_id}",
                "ClientId": client_id,
            }
        ],
    )["IdentityPoolId"]
    pool = CognitoPool(endpoint_url, pool_id, client_id, identity_pool_id)
    pool.add_user(EMAIL)
    return pool


@dataclass
class FakeMaveoApi:
    """In-memory state behind the fake REST admin endpoint."""

    devices: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": DEVICE_ID, "name": DEVICE_NAME, "devicetype": 1}
        ]
    )
    guests: list[dict[str, str]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    authorizations: list[str] = field(default_factory=list)
    fail_with: int | None = None
    next_guest: int = 0

    async def handle(self, request: web.Request) -> web.Response:
        payload: dict[str, Any] = await request.json()
        self.requests.append(payload)
        self.authorizations.append(request.headers.get("Authorization", ""))
        if self.fail_with is not None:
            return web.Response(
                text="secret-guest-token-in-error-body", status=self.fail_with
            )
        command = payload["command"]
        if command == "list_device":
            return web.json_response(self.devices)
        if command == "list_user":
            return web.json_response(self.guests)
        if command == "add_user":
            self.next_guest += 1
            guest = {
                "userid": f"guest-{self.next_guest:04d}-0000-0000-000000000000",
                "token": f"token{self.next_guest:04d}",
                "rights": str(payload["rights"]),
                "ttl": "4102444800",
                "nametag1": "",
                "nametag2": "",
                "nametag3": "",
            }
            self.guests.append(guest)
            return web.json_response(guest, status=201)
        if command == "remove_user":
            self.guests = [g for g in self.guests if g["userid"] != payload["userid"]]
            return web.json_response({})
        return web.Response(text="unknown command", status=400)

    def commands(self) -> list[str]:
        return [r["command"] for r in self.requests]


# Replies of a Connect stick (no H+T sensor) to the coordinator's read commands.
STICK_REPLIES: dict[str, dict[str, Any]] = {
    "AtoS_s": {"StoA_s": 4},
    "AtoS_v": {"StoA_v": "1.2.0"},
    "AtoS_l_r": {"StoA_l_r": 1},
    "AtoS_get_serial": {"StoA_serial": "SN0001"},
    "AtoS_name_r": {"StoA_name_r": DEVICE_NAME},
    "AtoS_ttc_r": {"StoA_ttc_r": 5},
    "AtoS_buzzer_r": {"StoA_buzzer_r": 0},
    "AtoS_gps_req": {"StoA_gps": 0, "lat": 51.5, "lng": -0.12},
    "AtoS_wifi_ap": {"ssid": "home", "ip": "192.168.0.50", "mac": "aa:bb", "rssi": -61},
    "AtoS_req_ime_learn": {"StoA_ime_learn": 0, "open": 1, "close": 0},
    "AtoS_sensor": {"StoA_sensor": 0, "command": 0, "error": 2},
    "AtoS_weather": {"StoA_weather": 0, "temperature": 1234, "humidity": 5600},
}


# H+T sensor readings and metadata, as sent in reply to Command.SENSOR_FULL.
HT_SENSOR_REPLY: dict[str, Any] = {
    "StoA_sensor": 0,
    "temperature_val": 2150,
    "humidity_val": 4520,
    "battery_val": 87,
    "last_update": 1700000000,
    "name": "Hall",
    "manufacturer": "Marantec",
    "model": "HT-1",
    "serial_num": "HT0001",
    "firmware_rev": "1.0",
    "software_rev": "",
    "hardware_rev": "A",
}


class FakeStick:
    """Garage sticks reachable over MQTT-over-WebSocket.

    `replies` maps a command key to the stick's answer. `bluefi` sends a
    state dump before the door status, as a BlueFi stick does. `ht_sensor`
    answers the indoor sensor commands as a paired sensor. `reachable=False`
    makes the WebSocket handshake fail, as when AWS IoT is unreachable.
    """

    def __init__(self) -> None:
        self.replies = dict(STICK_REPLIES)
        self.commands: list[dict[str, Any]] = []
        self.connect_headers: list[dict[str, str]] = []
        self.reachable = True
        self.connack_code = 0
        self.bluefi = False
        self.ht_sensor: dict[str, Any] | None = None

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if not self.reachable:
            return web.Response(status=503)
        self.connect_headers.append(dict(request.headers))
        ws = web.WebSocketResponse(protocols=("mqtt",))
        await ws.prepare(request)
        async for msg in ws:
            if msg.type is not WSMsgType.BINARY:
                break
            for reply in self._replies_to(msg.data):
                await ws.send_bytes(reply)
        return ws

    def _replies_to(self, data: bytes) -> list[bytes]:
        packet_type = data[0] >> 4
        if packet_type == 1:  # CONNECT
            return [bytes([0x20, 0x02, 0x00, self.connack_code])]
        if packet_type == 8:  # SUBSCRIBE
            return [b"\x90\x03\x00\x01\x00"]
        if packet_type == 3:  # PUBLISH
            packet = iot._parse_mqtt_packet(data)
            device_id = packet["topic"].split("/")[0]
            command: dict[str, Any] = packet["json"]
            self.commands.append(command)
            return [
                iot._mqtt_publish_packet(f"{device_id}/rsp", json.dumps(r).encode())
                for r in self._answer(command)
            ]
        return []

    def _answer(self, command: dict[str, Any]) -> list[dict[str, Any]]:
        if self.bluefi and "AtoS_s" in command and "AtoS_s" in self.replies:
            return [{"StoA_l_r": 1}, {"StoA_buzzer_r": 0}, self.replies["AtoS_s"]]
        if self.ht_sensor is not None and "AtoS_sensor" in command:
            if command.get("command") == 0:
                return [{"StoA_sensor": 0, "command": 0, "error": 0}]
            if command.get("command") == 8:
                return [self.ht_sensor, {"state": 9}]
        for key, reply in self.replies.items():
            if key in command:
                return [reply]
        return []


def create_app(api: FakeMaveoApi, stick: FakeStick) -> web.Application:
    app = web.Application()
    app.router.add_post("/admin", api.handle)
    app.router.add_get("/mqtt", stick.handle)
    return app
