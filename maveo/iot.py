"""
Maveo IoT WebSocket client.

Communicates with AWS IoT Core over MQTT-over-WebSocket using SigV4 auth.

MQTT topic format (confirmed via live testing):
  {device_id}/cmd  — app → device (publish commands here)
  {device_id}/rsp  — device → app (subscribe here for responses)

The session UUID from get_device_status() is NOT used in MQTT topics;
it is only relevant for checking whether the device is online.
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
    # Actions
    LIGHT_ON          = {"AtoS_l": 1}
    LIGHT_OFF         = {"AtoS_l": 0}
    GARAGE_OPEN       = {"AtoS_g": 1}   # confirmed live: opens door
    GARAGE_CLOSE      = {"AtoS_g": 2}   # confirmed live: closes door
    GARAGE_STOP       = {"AtoS_g": 0}   # confirmed live: stops door mid-travel
    GARAGE_VENTILATE  = {"AtoS_g": 3}   # ventilation position (which intermediate position is used: conflicting docs)
    # Read commands
    STATUS        = {"AtoS_s": 0}   # → StoA_s: door position int
                                     #   NOTE: also triggers a full state dump (see docs/iot-mqtt.md):
                                     #   weather, ventilation, sensor, GPS, WiFi, ime_learn — StoA_s arrives last
    VERSION       = {"AtoS_v": 0}   # → StoA_v: firmware version string (e.g. "1.2.0")
    LIGHT_READ    = {"AtoS_l_r": 0} # → StoA_l_r: light state (0=off, 1=on)
    SERIAL        = {"AtoS_get_serial": 0}  # → StoA_serial: serial number string
    NAME_READ     = {"AtoS_name_r": 0}      # → StoA_name_r: device name string
    TTC_READ      = {"AtoS_ttc_r": 0}       # → StoA_ttc_r: time-to-close minutes (0=disabled)
    BUZZER_READ   = {"AtoS_buzzer_r": 0}    # → StoA_buzzer_r: buzzer state string
    GPS_READ      = {"AtoS_gps_req": 0}     # → StoA_gps: {lat, lng} or 0 if unavailable
    WIFI_READ     = {"AtoS_wifi_ap": 0}     # → StoA_wifi_ap: {ssid, ip, mac, rssi, error}
    # Commands found in binary / confirmed in STATUS dump (payload value TBC)
    SENSOR_READ   = {"AtoS_sensor": 0}      # → StoA_sensor: {command, error, bt_addr} / {update_interval}
    VENTILATION_READ = {"AtoS_ventilation": 0}  # → StoA_ventilation: runtime state + config
    WEATHER_READ  = {"AtoS_weather": 0}     # → StoA_weather: {humidity (0.01%), temperature (0.01°C), last_update}
    IME_LEARN_READ = {"AtoS_req_ime_learn": 0}  # → StoA_ime_learn: {open, close} (1=learned)


# Door position enum (DoorPosition) from binary string table, sequential from 0.
# Value 4 = Closed confirmed via live test.
DOOR_STOPPED              = 0   # stopped mid-course (any direction)
DOOR_OPENING              = 1
DOOR_CLOSING              = 2
DOOR_OPEN                 = 3
DOOR_CLOSED               = 4
DOOR_INTERMEDIATE_OPEN    = 5   # stopped at the Intermediate Open position (higher partial-open)
DOOR_INTERMEDIATE_CLOSED  = 6   # stopped at the Intermediate Closed position (lower partial-open)

DOOR_POSITION_NAMES = {
    DOOR_STOPPED:             "Stopped",
    DOOR_OPENING:             "Opening",
    DOOR_CLOSING:             "Closing",
    DOOR_OPEN:                "Open",
    DOOR_CLOSED:              "Closed",
    DOOR_INTERMEDIATE_OPEN:   "IntermediateOpen",
    DOOR_INTERMEDIATE_CLOSED: "IntermediateClosed",
}


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


def _decode_remaining_length(data: bytes) -> tuple[int, int]:
    """
    Decode the MQTT variable-length remaining-length field starting at data[1].
    Returns (value, number_of_bytes_consumed).
    """
    value = 0
    for i, byte in enumerate(data[1:5]):   # up to 4 bytes
        value |= (byte & 0x7F) << (7 * i)
        if not (byte & 0x80):
            return value, i + 1
    raise ValueError("Malformed remaining-length field")


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

    try:
        _, rl_size = _decode_remaining_length(data)
    except ValueError:
        return result
    hdr = 1 + rl_size   # offset where variable header / payload start

    if msg_type == 2 and len(data) >= hdr + 2:   # CONNACK
        result["return_code"] = data[hdr + 1]

    elif msg_type == 3 and len(data) > hdr + 2:  # PUBLISH
        topic_len = int.from_bytes(data[hdr:hdr + 2], "big")
        body_start = hdr + 2 + topic_len
        if len(data) >= body_start:
            result["topic"]   = data[hdr + 2:body_start].decode(errors="replace")
            raw_payload       = data[body_start:]
            result["payload"] = raw_payload.decode(errors="replace")
            try:
                result["json"] = json.loads(raw_payload)
            except json.JSONDecodeError:
                pass

    elif msg_type == 9 and len(data) >= hdr + 3:  # SUBACK
        result["packet_id"]   = int.from_bytes(data[hdr:hdr + 2], "big")
        result["granted_qos"] = list(data[hdr + 2:])

    return result


# ---------------------------------------------------------------------------
# IoT client
# ---------------------------------------------------------------------------

class MaveoIoTClient:
    """
    MQTT over WebSocket client for Maveo device control.

    MQTT topic format (confirmed via live PCAP + testing):
      {device_id}/cmd  — publish commands here
      {device_id}/rsp  — subscribe here for responses

    The session UUID from get_device_status() is NOT used in topics; it is
    only useful for checking device online state before connecting.

    Usage (async):
        async with MaveoIoTClient(auth, config, device_id) as client:
            await client.send(Command.STATUS)
            pkt = await client.receive()

    AWS IoT policy requires MQTT client_id == device_id.
    WARNING: connecting kicks the stick's own MQTT session; it will reconnect
    automatically (typically within a few seconds).
    """

    def __init__(self, auth: AuthResult, config: Config, device_id: str,
                 _device_session: str = ""):
        """
        Parameters
        ----------
        auth          : AuthResult from maveo.auth.authenticate()
        config        : Config from maveo.config.get_config()
        device_id     : numeric device ID string from list_devices()
        _device_session: deprecated, ignored — kept for backwards compatibility
        """
        self._auth      = auth
        self._config    = config
        self._device_id = device_id
        self._ws        = None
        self._cmd_topic = f"{device_id}/cmd"
        self._rsp_topic = f"{device_id}/rsp"

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
        Defaults to {device_id}/rsp — the device response topic.
        """
        topic = topic or self._rsp_topic
        await self._ws.send(_mqtt_subscribe_packet(topic, packet_id=1))
        data = await asyncio.wait_for(self._ws.recv(), timeout=10)
        return _parse_mqtt_packet(data)

    async def send(self, command: dict) -> None:
        """Publish a command to {session}/cmd."""
        payload = json.dumps(command).encode()
        await self._ws.send(_mqtt_publish_packet(self._cmd_topic, payload))

    async def receive(self, timeout: float = 5.0) -> dict | None:
        """Wait for an incoming MQTT packet. Returns None on timeout or connection close."""
        try:
            data = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            return _parse_mqtt_packet(data)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
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
