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
    python cli.py status <device_id>           # cloud connectivity + session UUID
    python cli.py serial <device_id>           # hardware serial number
    python cli.py certificate <device_id>      # X.509 cert + private key
    python cli.py guests <device_id>           # list guest users
    python cli.py add-guest <device_id> <ttl>  # create guest user (ttl in seconds)
    python cli.py remove-guest <device_id> <user_id>
    python cli.py rename <device_id> <new_name>
    python cli.py --region US devices
"""

import argparse
import asyncio
import getpass
import os
import sys

from maveo import authenticate, get_config, Command, MaveoClient, MaveoIoTClient, Region
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


def cmd_serial(config, device_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    serial = client.get_device_serial(device_id)
    print(f"Serial : {serial}")


def cmd_certificate(config, device_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    info = client.get_device_certificate(device_id)
    print(f"Serial      : {info.serial}")
    print(f"Certificate :\n{info.certificate}")
    print(f"Private key :\n{info.private_key}")


def cmd_guests(config, device_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    users = client.list_guest_users(device_id)
    if not users:
        print("No guest users.")
        return
    print(f"Found {len(users)} guest user(s):")
    for u in users:
        tags = " / ".join(t for t in [u.nametag1, u.nametag2, u.nametag3] if t)
        print(f"  [{u.user_id}]  rights={u.rights}  ttl={u.ttl}"
              + (f"  ({tags})" if tags else ""))


def cmd_add_guest(config, device_id: str, ttl: int):
    auth = _login(config)
    client = MaveoClient(auth, config)
    u = client.add_guest_user(device_id, ttl)
    print(f"Guest user created:")
    print(f"  user_id : {u.user_id}")
    print(f"  token   : {u.token}")
    print(f"  rights  : {u.rights}")
    print(f"  ttl     : {u.ttl}")


def cmd_remove_guest(config, device_id: str, user_id: str):
    auth = _login(config)
    client = MaveoClient(auth, config)
    client.remove_guest_user(device_id, user_id)
    print(f"Guest user {user_id} removed.")


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

    # Get the session UUID needed for MQTT topic
    status = client.get_device_status(device_id)
    if not status.session:
        print("Device has no active session (offline?)", file=sys.stderr)
        sys.exit(1)
    print(f"Session : {status.session}")
    print(f"Sending : {action} → {_ACTIONS[action]}")

    async def _run():
        async with MaveoIoTClient(auth, config, status.session, device_id) as iot:
            print("WebSocket connected")
            # Subscribe to response topic first (matches real app PCAP behaviour)
            suback = await iot.subscribe()
            print(f"Subscribed ({status.session}/rsp): {suback}")
            await iot.send(_ACTIONS[action])
            print("Command sent. Listening for responses...")
            deadline = asyncio.get_event_loop().time() + listen
            while asyncio.get_event_loop().time() < deadline:
                pkt = await iot.receive(timeout=1.0)
                if pkt:
                    print(f"  << {pkt}")

    asyncio.run(_run())


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
    sub.add_parser("configure",   help="Save credentials to the OS keychain")
    sub.add_parser("logout",      help="Remove credentials from the OS keychain")
    sub.add_parser("login",       help="Test login and show identity info")
    sub.add_parser("devices",     help="List all devices")

    p = sub.add_parser("status",      help="Get device cloud status + session UUID")
    p.add_argument("device_id")

    p = sub.add_parser("serial",      help="Get device hardware serial number")
    p.add_argument("device_id")

    p = sub.add_parser("certificate", help="Get device X.509 certificate and private key")
    p.add_argument("device_id")

    p = sub.add_parser("guests",      help="List guest users for a device")
    p.add_argument("device_id")

    p = sub.add_parser("add-guest",   help="Create a guest user (ttl in seconds)")
    p.add_argument("device_id")
    p.add_argument("ttl", type=int)

    p = sub.add_parser("remove-guest", help="Remove a guest user")
    p.add_argument("device_id")
    p.add_argument("user_id")

    p = sub.add_parser("control",     help="Send IoT command to a device")
    p.add_argument("device_id")
    p.add_argument("action", choices=list(_ACTIONS))
    p.add_argument("--listen", type=float, default=5.0,
                   metavar="SECS", help="Seconds to listen for responses (default: 5)")

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

    config = get_config(Region(args.region))

    try:
        if args.command == "login":
            cmd_login(config)
        elif args.command == "devices":
            cmd_devices(config)
        elif args.command == "status":
            cmd_status(config, args.device_id)
        elif args.command == "serial":
            cmd_serial(config, args.device_id)
        elif args.command == "certificate":
            cmd_certificate(config, args.device_id)
        elif args.command == "guests":
            cmd_guests(config, args.device_id)
        elif args.command == "add-guest":
            cmd_add_guest(config, args.device_id, args.ttl)
        elif args.command == "remove-guest":
            cmd_remove_guest(config, args.device_id, args.user_id)
        elif args.command == "control":
            cmd_control(config, args.device_id, args.action, args.listen)
        elif args.command == "rename":
            cmd_rename(config, args.device_id, args.name)
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
