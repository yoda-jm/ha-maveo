#!/usr/bin/env python3
"""
Maveo CLI — quick tool to play with the Maveo cloud API.

Credentials are resolved in this order:
  1. Environment variables  MAVEO_EMAIL / MAVEO_PASSWORD
  2. OS keychain            (after running: python cli.py configure)
  3. Interactive prompt     (fallback)

Usage:
    python cli.py configure                    # save credentials to OS keychain
    python cli.py login                        # test login
    python cli.py devices                      # list devices
    python cli.py status <device_id>           # cloud connectivity (CONNECTED/offline)
    python cli.py guests <device_id>           # list guest users
    python cli.py add-guest <device_id> <ttl> [--admin]  # create guest (default: restricted)
    python cli.py edit-guest <device_id> <user_id> [--admin|--restricted] [--name NAME]
    python cli.py remove-guest <device_id> <user_id>
    python cli.py share-guest <device_id> <user_id> [--name NAME] [--location LOC] [--latitude LAT] [--longitude LON]
    python cli.py decode-link <url>            # decrypt a guest deep link
    python cli.py rename <device_id> <new_name>
    python cli.py info <device_id>             # query all IoT sensors and display
    python cli.py firebase-token               # get Firebase Installation auth token
    python cli.py firebase-rc                  # fetch Firebase Remote Config
    python cli.py pro-customer                 # MaveoPro profile + devices (api.yourgateway.io)
    python cli.py --region US devices
"""

import argparse
import asyncio
import getpass
import os
import sys

from maveo import (authenticate, get_config, Command, MaveoClient, MaveoIoTClient,
                   Region, RIGHTS_ADMIN, RIGHTS_RESTRICTED, decode_guest_link,
                   get_installation_token, fetch_remote_config, FirebaseError,
                   MaveoProClient, MaveoProError, DOOR_POSITION_NAMES)
from maveo.auth import AuthError
from maveo.client import APIError

KEYRING_SERVICE = "maveo"
KEYRING_EMAIL_KEY = "_account"


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def get_credentials() -> tuple[str, str]:
    email = os.environ.get("MAVEO_EMAIL")
    password = os.environ.get("MAVEO_PASSWORD")

    if email and password:
        return email, password

    kr = _keyring()
    if kr:
        stored_email = kr.get_password(KEYRING_SERVICE, KEYRING_EMAIL_KEY)
        if stored_email:
            stored_password = kr.get_password(KEYRING_SERVICE, stored_email)
            if stored_password:
                email = email or stored_email
                password = password or stored_password
                if email and password:
                    return email, password

    if not email:
        email = input("Email: ").strip()
    if not password:
        password = getpass.getpass("Password: ")

    return email, password


def save_credentials(email: str, password: str) -> None:
    kr = _keyring()
    if kr is None:
        print("keyring is not installed — run:  pip install keyring", file=sys.stderr)
        sys.exit(1)
    kr.set_password(KEYRING_SERVICE, KEYRING_EMAIL_KEY, email)
    kr.set_password(KEYRING_SERVICE, email, password)


def delete_credentials() -> None:
    kr = _keyring()
    if kr is None:
        return
    email = kr.get_password(KEYRING_SERVICE, KEYRING_EMAIL_KEY)
    if email:
        kr.delete_password(KEYRING_SERVICE, email)
        kr.delete_password(KEYRING_SERVICE, KEYRING_EMAIL_KEY)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_configure():
    print("Enter your Maveo credentials (stored in the OS keychain).")
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    save_credentials(email, password)
    print(f"Credentials for {email} saved.")


def cmd_logout():
    delete_credentials()
    print("Credentials removed from keychain.")


def _login(config):
    email, password = get_credentials()
    print(f"Authenticating as {email}...")
    auth = authenticate(email, password, config)
    return auth


def cmd_login(config):
    auth = _login(config)
    print(f"  identity_id : {auth.identity_id}")
    print(f"  expires     : {auth.expiration}")


def cmd_devices(config):
    auth = _login(config)
    client = MaveoClient(auth, config)
    devices = client.list_devices()
    if not devices:
        print("No devices found.")
        return
    print(f"Found {len(devices)} device(s):")
    for d in devices:
        print(f"  [{d.id}]  {d.name}  (type={d.device_type})")


def cmd_status(config, device_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    s = client.get_device_status(device_id)
    print(f"Device  : {s.device}")
    print(f"Mobile  : {s.mobile}")
    print(f"Session : {s.session}")


def cmd_guests(config, device_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    users = client.list_guest_users(device_id)
    if not users:
        print("No guest users.")
        return
    print(f"Found {len(users)} guest user(s):")
    for u in users:
        level = "admin" if u.rights == "1" else "restricted"
        tags = " / ".join(t for t in [u.nametag1, u.nametag2, u.nametag3] if t)
        claimed = "claimed" if u.is_claimed else "unclaimed"
        print(f"  [{u.user_id}]  {level}  {claimed}  ttl={u.ttl}"
              + (f"  ({tags})" if tags else ""))


def cmd_add_guest(config, device_id: str, ttl: int, admin: bool):
    auth = _login(config)
    client = MaveoClient(auth, config)
    rights = RIGHTS_ADMIN if admin else RIGHTS_RESTRICTED
    u = client.add_guest_user(device_id, ttl, rights=rights)
    print(f"Guest user created:")
    print(f"  user_id : {u.user_id}")
    print(f"  token   : {u.token}")
    print(f"  rights  : {'admin' if u.rights == '1' else 'restricted'}")
    print(f"  ttl     : {u.ttl}")


def cmd_edit_guest(config, device_id: str, user_id: str,
                   rights: int | None, name: str | None):
    auth = _login(config)
    client = MaveoClient(auth, config)
    client.edit_guest_user(device_id, user_id,
                           rights=rights,
                           nametag1=name)
    print(f"Guest user {user_id} updated.")


def cmd_remove_guest(config, device_id: str, user_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    client.remove_guest_user(device_id, user_id)
    print(f"Guest user {user_id} removed.")


def _fetch_device_info(auth, config, device_id: str, need_gps: bool, need_name: bool) -> dict:
    """Fetch device name and/or GPS from the stick via MQTT."""
    result = {}

    async def _run():
        async with MaveoIoTClient(auth, config, device_id) as iot:
            await iot.subscribe()
            if need_name:
                await iot.send(Command.NAME_READ)
                pkt = await iot.receive(timeout=3.0)
                if pkt and "json" in pkt:
                    result["name"] = pkt["json"].get("StoA_name_r", "")
            if need_gps:
                await iot.send(Command.GPS_READ)
                pkt = await iot.receive(timeout=3.0)
                if pkt and "json" in pkt:
                    d = pkt["json"]
                    if d.get("StoA_gps") == 0:
                        result["lat"] = d.get("lat", 0.0)
                        result["lng"] = d.get("lng", 0.0)

    asyncio.run(_run())
    return result


def cmd_share_guest(config, device_id: str, user_id: str,
                    device_name: str | None, location_name: str | None,
                    latitude: float | None, longitude: float | None):
    auth = _login(config)
    client = MaveoClient(auth, config)
    users = client.list_guest_users(device_id)
    guest = next((u for u in users if u.user_id == user_id), None)
    if guest is None:
        print(f"Guest user {user_id} not found.", file=sys.stderr)
        sys.exit(1)

    need_name = device_name is None
    need_gps  = latitude is None or longitude is None

    if need_name or need_gps:
        print("Fetching device data from stick via MQTT...")
        info = _fetch_device_info(auth, config, device_id, need_gps=need_gps, need_name=need_name)
        if need_name:
            device_name = info.get("name") or device_id
        if need_gps:
            latitude  = info.get("lat", 0.0)
            longitude = info.get("lng", 0.0)

    if location_name is None:
        location_name = device_name

    link = client.generate_guest_link(
        guest, device_id, device_name,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
    )
    print(link)


def cmd_decode_link(url: str):
    try:
        payload = decode_guest_link(url)
    except ValueError as e:
        print(f"Failed to decode link: {e}", file=sys.stderr)
        sys.exit(1)
    for k, v in payload.items():
        print(f"  {k:15s} : {v}")


_ACTIONS = {
    "light-on":     Command.LIGHT_ON,
    "light-off":    Command.LIGHT_OFF,
    "garage-open":  Command.GARAGE_OPEN,
    "garage-close": Command.GARAGE_CLOSE,
    "garage-stop":  Command.GARAGE_STOP,
    "status":       Command.STATUS,
}

def cmd_control(config, device_id: str, action: str, listen: float):
    auth = _login(config)
    client = MaveoClient(auth, config)

    # Check device is online (session UUID is not needed for MQTT topics)
    status = client.get_device_status(device_id)
    if status.device != "CONNECTED":
        print("Device is offline.", file=sys.stderr)
        sys.exit(1)
    print(f"Device  : {status.device}")
    print(f"Sending : {action} → {_ACTIONS[action]}")

    async def _run():
        async with MaveoIoTClient(auth, config, device_id) as iot:
            print("WebSocket connected")
            suback = await iot.subscribe()
            print(f"Subscribed ({device_id}/rsp): {suback}")
            await iot.send(_ACTIONS[action])
            print("Command sent. Listening for responses...")
            deadline = asyncio.get_event_loop().time() + listen
            while asyncio.get_event_loop().time() < deadline:
                pkt = await iot.receive(timeout=1.0)
                if pkt:
                    print(f"  << {pkt}")

    asyncio.run(_run())


def cmd_info(config, device_id: str):
    """Query all IoT read commands and display results in a human-readable form."""
    auth = _login(config)
    client = MaveoClient(auth, config)

    status = client.get_device_status(device_id)
    if status.device != "CONNECTED":
        print("Device is offline.", file=sys.stderr)
        sys.exit(1)

    READ_COMMANDS = [
        ("Door status",     Command.STATUS),
        ("Firmware",        Command.VERSION),
        ("Light",           Command.LIGHT_READ),
        ("Serial",          Command.SERIAL),
        ("Device name",     Command.NAME_READ),
        ("Time-to-close",   Command.TTC_READ),
        ("Buzzer",          Command.BUZZER_READ),
        ("GPS",             Command.GPS_READ),
        ("WiFi",            Command.WIFI_READ),
    ]

    async def _run():
        results = {}
        async with MaveoIoTClient(auth, config, device_id) as iot:
            await iot.subscribe()
            for label, cmd in READ_COMMANDS:
                await iot.send(cmd)
                pkt = await iot.receive(timeout=3.0)
                if pkt and "json" in pkt:
                    results[label] = pkt["json"]
                else:
                    results[label] = None
        return results

    results = asyncio.run(_run())

    print(f"{'Device ID':<20}: {device_id}")
    print(f"{'Cloud status':<20}: {status.device}")
    print()

    for label, data in results.items():
        if data is None:
            print(f"  {label:<18}: (no response)")
            continue

        if label == "Door status":
            val = data.get("StoA_s")
            name = DOOR_POSITION_NAMES.get(val, f"unknown({val})")
            print(f"  {label:<18}: {name} (raw={val})")
        elif label == "Firmware":
            print(f"  {label:<18}: {data.get('StoA_v', '?')}")
        elif label == "Light":
            val = data.get("StoA_l_r")
            print(f"  {label:<18}: {'on' if val else 'off'}")
        elif label == "Serial":
            print(f"  {label:<18}: {data.get('StoA_serial', '?')}")
        elif label == "Device name":
            print(f"  {label:<18}: {data.get('StoA_name_r', '?')}")
        elif label == "Time-to-close":
            val = data.get("StoA_ttc_r", 0)
            print(f"  {label:<18}: {'disabled' if val == 0 else f'{val} min'}")
        elif label == "Buzzer":
            val = data.get("StoA_buzzer_r")
            print(f"  {label:<18}: {'on' if val else 'off'}")
        elif label == "GPS":
            if data.get("StoA_gps") == 0:
                print(f"  {label:<18}: lat={data.get('lat')}, lng={data.get('lng')}")
            else:
                print(f"  {label:<18}: unavailable")
        elif label == "WiFi":
            ssid = data.get("ssid", "?")
            ip   = data.get("ip", "?")
            mac  = data.get("mac", "?")
            rssi = data.get("rssi", "?")
            print(f"  {label:<18}: ssid={ssid}  ip={ip}  mac={mac}  rssi={rssi} dBm")


def cmd_firebase_token():
    """Obtain a Firebase Installation auth token for the Maveo app project."""
    try:
        tok = get_installation_token()
    except FirebaseError as e:
        print(f"Firebase error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"fid         : {tok.fid}")
    print(f"auth_token  : {tok.auth_token}")
    print(f"expires_in  : {tok.expires_in}")
    print(f"refresh_tok : {tok.refresh_token}")


def cmd_firebase_rc():
    """Fetch Firebase Remote Config using a freshly obtained installation token."""
    try:
        tok = get_installation_token()
        rc = fetch_remote_config(tok)
    except FirebaseError as e:
        print(f"Firebase error: {e}", file=sys.stderr)
        sys.exit(1)
    import json
    print(json.dumps(rc, indent=2))


def cmd_pro_customer(config, email: str):
    auth = _login(config)
    pro = MaveoProClient(auth, email)
    c = pro.get_customer()
    print(f"Name    : {c.full_name}")
    print(f"Email   : {c.email}")
    if c.phone:
        print(f"Phone   : {c.phone}")
    if c.address_formatted:
        print(f"Address : {c.address_formatted}")
    if c.created:
        print(f"Created : {c.created}")
    if c.updated:
        print(f"Updated : {c.updated}")
    if not c.devices:
        print("Devices : (none)")
    else:
        print(f"Devices : {len(c.devices)}")
        for d in c.devices:
            print(f"  [{d.serial_number}]  type={d.device_type}")


def cmd_rename(config, device_id: str, name: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    client.set_device_name(device_id, name)
    print(f"Device {device_id} renamed to '{name}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Maveo CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Credentials priority: MAVEO_EMAIL/MAVEO_PASSWORD env vars"
            " → OS keychain (configure) → interactive prompt"
        ),
    )
    parser.add_argument(
        "--region", choices=["EU", "US"], default="EU",
        help="API region (default: EU)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("configure",    help="Save credentials to the OS keychain")
    sub.add_parser("logout",       help="Remove credentials from the OS keychain")
    sub.add_parser("login",        help="Test login and show identity info")
    sub.add_parser("devices",      help="List all devices")
    sub.add_parser("firebase-token", help="Get a Firebase Installation auth token (Maveo app project)")
    sub.add_parser("firebase-rc",  help="Fetch Firebase Remote Config (Maveo app project)")

    p = sub.add_parser("status",      help="Get device cloud status + session UUID")
    p.add_argument("device_id")

    p = sub.add_parser("guests",      help="List guest users for a device")
    p.add_argument("device_id")

    p = sub.add_parser("add-guest",   help="Create a guest user (ttl in seconds)")
    p.add_argument("device_id")
    p.add_argument("ttl", type=int)
    p.add_argument("--admin", action="store_true",
                   help="Grant admin rights (default: restricted/geofence)")

    p = sub.add_parser("edit-guest",  help="Edit a guest user (rights or name)")
    p.add_argument("device_id")
    p.add_argument("user_id")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--admin",      action="store_true", help="Set rights to admin")
    grp.add_argument("--restricted", action="store_true", help="Set rights to restricted")
    p.add_argument("--name", metavar="NAME", help="Set nametag1")

    p = sub.add_parser("remove-guest", help="Remove a guest user")
    p.add_argument("device_id")
    p.add_argument("user_id")

    p = sub.add_parser("share-guest", help="Generate a shareable deep link for a guest user")
    p.add_argument("device_id")
    p.add_argument("user_id")
    p.add_argument("--name",      metavar="NAME",  default=None,
                   help="Garage display name (default: fetched from device)")
    p.add_argument("--location",  metavar="NAME",  default=None,
                   help="Location name (default: same as --name)")
    p.add_argument("--latitude",  type=float,      default=None,
                   help="GPS latitude (default: fetched from device)")
    p.add_argument("--longitude", type=float,      default=None,
                   help="GPS longitude (default: fetched from device)")

    p = sub.add_parser("decode-link", help="Decode (decrypt) a guest deep link URL")
    p.add_argument("url", help="The deeplink.marantec-cloud.de URL")

    p = sub.add_parser("info",        help="Query all IoT read commands and display device info")
    p.add_argument("device_id")

    p = sub.add_parser("control",     help="Send IoT command to a device")
    p.add_argument("device_id")
    p.add_argument("action", choices=list(_ACTIONS))
    p.add_argument("--listen", type=float, default=5.0,
                   metavar="SECS", help="Seconds to listen for responses (default: 5)")

    p = sub.add_parser("pro-customer", help="Get MaveoPro customer profile + devices")
    p.add_argument("--email", metavar="EMAIL",
                   help="Account email (default: uses stored/env credentials)")

    p = sub.add_parser("rename",      help="Rename a device")
    p.add_argument("device_id")
    p.add_argument("name")

    args = parser.parse_args()

    if args.command == "configure":
        cmd_configure()
        return
    if args.command == "logout":
        cmd_logout()
        return
    if args.command == "decode-link":
        cmd_decode_link(args.url)
        return
    if args.command == "firebase-token":
        cmd_firebase_token()
        return
    if args.command == "firebase-rc":
        cmd_firebase_rc()
        return

    config = get_config(Region(args.region))

    try:
        if args.command == "login":
            cmd_login(config)
        elif args.command == "devices":
            cmd_devices(config)
        elif args.command == "status":
            cmd_status(config, args.device_id)
        elif args.command == "guests":
            cmd_guests(config, args.device_id)
        elif args.command == "add-guest":
            cmd_add_guest(config, args.device_id, args.ttl, args.admin)
        elif args.command == "edit-guest":
            rights = RIGHTS_ADMIN if args.admin else (RIGHTS_RESTRICTED if args.restricted else None)
            cmd_edit_guest(config, args.device_id, args.user_id, rights, args.name)
        elif args.command == "remove-guest":
            cmd_remove_guest(config, args.device_id, args.user_id)
        elif args.command == "share-guest":
            cmd_share_guest(config, args.device_id, args.user_id, args.name,
                            args.location, args.latitude, args.longitude)
        elif args.command == "info":
            cmd_info(config, args.device_id)
        elif args.command == "control":
            cmd_control(config, args.device_id, args.action, args.listen)
        elif args.command == "pro-customer":
            email = args.email or get_credentials()[0]
            cmd_pro_customer(config, email)
        elif args.command == "rename":
            cmd_rename(config, args.device_id, args.name)
    except MaveoProError as e:
        print(f"MaveoPro error: {e}", file=sys.stderr)
        sys.exit(1)
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
