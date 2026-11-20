"""Create a one-use device pairing code — run LOCALLY on the server machine.

    python -m server.tools.create_device_pairing_code --role dashboard

Prints a code valid for five minutes. It is consumed by the first
``POST /api/auth/device/enroll`` and cannot be replayed. Pairing codes are never
issued from an unauthenticated web endpoint, so knowing the server address is
not enough to enroll a device.
"""

import argparse
import sys
import time

try:  # the CLI must see the same .env the server uses
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - optional dependency
    pass

from server.db import init_db
from server.systems.security.device_auth import (
    PAIRING_ROLES,
    PAIRING_TTL_SECONDS,
    DeviceAuthError,
    create_pairing_code,
    device_auth_enabled,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a one-use Aariya device pairing code.",
    )
    parser.add_argument(
        "--role",
        required=True,
        choices=sorted(PAIRING_ROLES),
        help="mobile for the phone, dashboard for the computer",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=PAIRING_TTL_SECONDS,
        help=f"seconds until the code expires (default {PAIRING_TTL_SECONDS})",
    )
    args = parser.parse_args(argv)

    if not device_auth_enabled():
        print(
            "AARIYA_OWNER_ID is not configured. "
            "Configure the existing Aariya owner before pairing.",
            file=sys.stderr,
        )
        return 2

    init_db()  # makes the tool usable before the server has booted once
    try:
        code = create_pairing_code(
            role=args.role,
            ttl_seconds=args.ttl,
        )
    except DeviceAuthError as exc:
        print(f"Cannot create pairing code: {exc}", file=sys.stderr)
        return 2

    expires = time.strftime("%H:%M:%S", time.localtime(time.time() + args.ttl))
    print()
    print(f"  Pairing code ({args.role}):  {code}")
    print(f"  Expires at:               {expires}  ({args.ttl}s, one use)")
    print()
    print("  Enter it on the device now. It cannot be recovered or reused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
