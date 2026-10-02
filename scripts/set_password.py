"""Set a user's password from the Mac's terminal — the admin's own override.

    python -m scripts.set_password gil                  # asks twice
    python -m scripts.set_password dana --allow-short   # ignores the admin's minimum

Everyone but the admin follows the admin's password policy (Account tab);
`--allow-short` sets any password, empty included. Existing sign-ins stay
signed in.
"""
from __future__ import annotations

import argparse
import getpass
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--allow-short", action="store_true")
    ap.add_argument("--password-stdin", action="store_true")
    a = ap.parse_args(argv)
    from assistant.users import registry
    uid = registry.by_username(a.username)
    if uid is None:
        print(f"no user {a.username!r}", file=sys.stderr)
        return 1
    if a.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("new password: ")
        if pw != getpass.getpass("again: "):
            print("the two passwords differ", file=sys.stderr)
            return 1
    registry.set_password(uid, pw, must_change=False,
                          min_length=0 if a.allow_short else None,
                          allow_empty=True if a.allow_short else None)
    print(f"password set for {a.username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
