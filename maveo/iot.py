"""
Maveo IoT WebSocket client.

Communicates with AWS IoT Core over MQTT-over-WebSocket using SigV4 auth.
The session UUID (from MaveoClient.get_device_status) is required to build
the command topic: {session}/cmd
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import websockets

from .auth import AuthResult
from .config import Config


# ---------------------------------------------------------------------------
# Commands (from decompiled libmaveo-app)
# ---------------------------------------------------------------------------

class Command:
    LIGHT_ON      = {"AtoS_l": True}
    LIGHT_OFF     = {"AtoS_l": False}
    GARAGE_OPEN   = {"AtoS_g": 1}
    GARAGE_CLOSE  = {"AtoS_g": 0}
    GARAGE_STOP   = {"AtoS_g": 2}
    STATUS        = {"AtoS_s": 0}


# ---------------------------------------------------------------------------
# SigV4 query-param signing for WebSocket
# ---------------------------------------------------------------------------

def _hmac_sha256(key: bytes | str, data: str) -> bytes:
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key, data.encode(), hashlib.sha256).digest()


def _sigv4_headers(hostname: str, region: str,
                   access_key: str, secret_key: str,
                   session_token: str) -> dict:
    """
    Build AWS SigV4 Authorization headers for MQTT-over-WebSocket.
    Uses header-based authentication (not query params).
    Service: iotdata  (discovered working service name for this endpoint).
    """
    now = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    service       = "iotdata"
    algorithm     = "AWS4-HMAC-SHA256"
    scope         = f"{date_stamp}/{region}/{service}/aws4_request"
    signed_headers = "host;x-amz-date;x-amz-security-token"

    canonical_headers = (
        f"host:{hostname}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-security-token:{session_token}\n"
    )
    canonical_request = "\n".join([
        "GET",
        "/mqtt",
        "",                                  # no query string
        canonical_headers,
        signed_headers,
        hashlib.sha256(b"").hexdigest(),
    ])

    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    k_date    = _hmac_sha256(f"AWS4{secret_key}".encode(), date_stamp)
    k_region  = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    signature = _hmac_sha256(k_signing, string_to_sign).hex()

    auth = (
        f"{algorithm} Credential={access_key}/{scope},"
        f" SignedHeaders={signed_headers},"
        f" Signature={signature}"
    )

    return {
        "Host":                  hostname,
        "X-Amz-Date":            amz_date,
        "X-Amz-Security-Token":  session_token,
        "Authorization":         auth,
        "User-Agent":            "MaveoApp/2.6.0",
    }


# ---------------------------------------------------------------------------
# MQTT packet helpers
# ---------------------------------------------------------------------------

def _encode_remaining_length(length: int) -> bytes:
    """MQTT variable-length remaining-length encoding."""
    result = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        if length:
            byte |= 0x80
        result.append(byte)
        if not length:
            break
    return bytes(result)


def _mqtt_connect_packet(client_id: str = "") -> bytes:
    """Build an MQTT 3.1.1 CONNECT packet."""
    protocol_name  = b"\x00\x04MQTT"
    protocol_level = b"\x04"          # MQTT 3.1.1
    connect_flags  = b"\x02"          # clean session only
    keep_alive     = b"\x00\x3c"      # 60 s

    client_id_bytes = client_id.encode()
    payload = (
        len(client_id_bytes).to_bytes(2, "big")
        + client_id_bytes
    )

    variable_header = protocol_name + protocol_level + connect_flags + keep_alive
    remaining = variable_header + payload

    return b"\x10" + _encode_remaining_length(len(remaining)) + remaining


def _mqtt_subscribe_packet(topic: str, packet_id: int = 1) -> bytes:
    """Build an MQTT SUBSCRIBE packet (QoS 0)."""
    topic_bytes = topic.encode()
    variable_header = packet_id.to_bytes(2, "big")
    payload = (
        len(topic_bytes).to_bytes(2, "big")
        + topic_bytes
        + b"\x00"   # requested QoS 0
    )
    remaining = variable_header + payload
    return b"\x82" + _encode_remaining_length(len(remaining)) + remaining


def _mqtt_publish_packet(topic: str, payload: bytes) -> bytes:
    """Build an MQTT PUBLISH packet (QoS 0, no retain, no dup)."""
    topic_bytes = topic.encode()
    variable_header = len(topic_bytes).to_bytes(2, "big") + topic_bytes
    remaining = variable_header + payload
    return b"\x30" + _encode_remaining_length(len(remaining)) + remaining


def _parse_mqtt_packet(data: bytes) -> dict:
    """Parse a received MQTT packet into a dict for logging/inspection."""
    if len(data) < 2:
        return {"type": "unknown", "raw": data.hex()}

    msg_type = (data[0] >> 4) & 0x0F
    names = {
        1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK",
        8: "SUBSCRIBE", 9: "SUBACK", 12: "PINGREQ", 13: "PINGRESP",
        14: "DISCONNECT",
    }
    result = {"type": names.get(msg_type, f"0x{data[0]:02x}"), "raw": data.hex()}

    if msg_type == 2 and len(data) >= 4:   # CONNACK
        result["return_code"] = data[3]

    elif msg_type == 3 and len(data) > 4:  # PUBLISH
        topic_len = int.from_bytes(data[2:4], "big")
        if len(data) >= 4 + topic_len:
            result["topic"]   = data[4:4 + topic_len].decode(errors="replace")
            raw_payload       = data[4 + topic_len:]
            result["payload"] = raw_payload.decode(errors="replace")
            try:
                result["json"] = json.loads(raw_payload)
            except json.JSONDecodeError:
                pass

    elif msg_type == 9 and len(data) >= 5:  # SUBACK
        result["packet_id"]   = int.from_bytes(data[2:4], "big")
        result["granted_qos"] = list(data[4:])

    return result


# ---------------------------------------------------------------------------
# IoT client
# ---------------------------------------------------------------------------

class MaveoIoTClient:
    """
    MQTT over WebSocket client for Maveo device control.

    Usage (async):
        async with MaveoIoTClient(auth, config, session_uuid, device_id) as client:
            await client.send(Command.LIGHT_ON)
            await client.send(Command.GARAGE_OPEN)

    session_uuid comes from MaveoClient.get_device_status(device_id).session
    device_id is required as the MQTT client ID (AWS IoT policy enforces this).
    """

    def __init__(self, auth: AuthResult, config: Config, device_session: str, device_id: str):
        self._auth      = auth
        self._config    = config
        self._session   = device_session
        self._device_id = device_id
        self._ws        = None
        self._cmd_topic = f"{device_session}/cmd"

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        """Open WebSocket, send MQTT CONNECT (client_id = device_id), wait for CONNACK."""
        headers = _sigv4_headers(
            hostname      = self._config.iot_hostname,
            region        = self._config.aws_region,
            access_key    = self._auth.access_key_id,
            secret_key    = self._auth.secret_key,
            session_token = self._auth.session_token,
        )
        self._ws = await websockets.connect(
            f"wss://{self._config.iot_hostname}/mqtt",
            subprotocols=["mqtt"],
            additional_headers=headers,
            open_timeout=15,
        )

        await self._ws.send(_mqtt_connect_packet(self._device_id))
        data = await asyncio.wait_for(self._ws.recv(), timeout=10)
        pkt  = _parse_mqtt_packet(data)
        if pkt.get("type") != "CONNACK":
            raise ConnectionError(f"Expected CONNACK, got: {pkt}")
        if pkt.get("return_code", 1) != 0:
            raise ConnectionError(f"MQTT connection refused, code: {pkt['return_code']}")

    async def subscribe(self, topic: str | None = None) -> dict:
        """
        Subscribe to a topic and return the SUBACK.
        Defaults to {session}/rsp — the response topic the real app subscribes
        to first (observed in PCAP: 66-byte SUBSCRIBE immediately after WS upgrade).
        """
        topic = topic or f"{self._session}/rsp"
        await self._ws.send(_mqtt_subscribe_packet(topic, packet_id=1))
        data = await asyncio.wait_for(self._ws.recv(), timeout=10)
        return _parse_mqtt_packet(data)

    async def send(self, command: dict) -> None:
        """Publish a command to {session}/cmd."""
        payload = json.dumps(command).encode()
        await self._ws.send(_mqtt_publish_packet(self._cmd_topic, payload))

    async def receive(self, timeout: float = 5.0) -> dict | None:
        """Wait for an incoming MQTT packet. Returns None on timeout."""
        try:
            data = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            return _parse_mqtt_packet(data)
        except asyncio.TimeoutError:
            return None

    async def ping(self) -> bool:
        """Send MQTT PINGREQ, return True if PINGRESP received."""
        await self._ws.send(b"\xc0\x00")
        pkt = await self.receive(timeout=5.0)
        return pkt is not None and pkt.get("type") == "PINGRESP"

    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None
