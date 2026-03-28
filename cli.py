#!/usr/bin/env python3
"""
Maveo CLI — quick tool to play with the Maveo cloud API.

Credentials are resolved in this order:
  1. Environment variables  MAVEO_EMAIL / MAVEO_PASSWORD
  2. OS keychain            (after running: python cli.py configure)
  3. Interactive prompt     (fallback)

Usage:
    python cli.py configure          # save credentials to OS keychain
    python cli.py login              # test login
    python cli.py devices            # list devices
    python cli.py status <device_id>
    python cli.py rename <device_id> <new_name>
    python cli.py --region US devices
"""

import argparse
import getpass
import os
import sys

from maveo import authenticate, get_config, MaveoClient, Region
from maveo.auth import AuthError
from maveo.client import APIError

KEYRING_SERVICE = "maveo"
KEYRING_EMAIL_KEY = "_account"  # slot that stores the email itself


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def _keyring():
    """Return the keyring module, or None if not installed."""
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def get_credentials() -> tuple[str, str]:
    """
    Resolve email + password using the priority chain:
      env vars → keyring → interactive prompt
    """
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

    # Interactive fallback
    if not email:
        email = input("Email: ").strip()
    if not password:
        password = getpass.getpass("Password: ")

    return email, password


def save_credentials(email: str, password: str) -> None:
    kr = _keyring()
    if kr is None:
        print(
            "keyring is not installed — run:  pip install keyring",
            file=sys.stderr,
        )
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


def cmd_login(config):
    email, password = get_credentials()
    print(f"Logging in as {email}...")
    auth = authenticate(email, password, config)
    print(f"  identity_id : {auth.identity_id}")
    print(f"  expires     : {auth.expiration}")


def cmd_devices(config):
    email, password = get_credentials()
    print(f"Authenticating as {email}...")
    auth = authenticate(email, password, config)
    client = MaveoClient(auth, config)
    devices = client.list_devices()
    if not devices:
        print("No devices found.")
        return
    print(f"Found {len(devices)} device(s):")
    for d in devices:
        print(f"  [{d.id}]  {d.name}  (type={d.device_type})")


def cmd_status(config, device_id: str):
    email, password = get_credentials()
    auth = authenticate(email, password, config)
    client = MaveoClient(auth, config)
    status = client.get_device_status(device_id)
    print(f"Device  : {status.device}")
    print(f"Mobile  : {status.mobile}")
    print(f"Session : {status.session}")


def cmd_rename(config, device_id: str, name: str):
    email, password = get_credentials()
    auth = authenticate(email, password, config)
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
    sub.add_parser("configure", help="Save credentials to the OS keychain")
    sub.add_parser("logout",    help="Remove credentials from the OS keychain")
    sub.add_parser("login",     help="Test login and show identity info")
    sub.add_parser("devices",   help="List all devices")

    p_status = sub.add_parser("status", help="Get device status")
    p_status.add_argument("device_id")

    p_rename = sub.add_parser("rename", help="Rename a device")
    p_rename.add_argument("device_id")
    p_rename.add_argument("name")

    args = parser.parse_args()

    # configure / logout don't need a region or network call
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
