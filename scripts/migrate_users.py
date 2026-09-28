"""Move today's data into the admin's folder (users, phase 1) — or back.

    python -m scripts.migrate_users --dry-run
    python -m scripts.migrate_users --apply --admin gil [--name Gil] [--password-stdin]
    python -m scripts.migrate_users --rollback

`assistant/users/migrate.py` has the order and why. The password is asked for
twice on the terminal (never an argument: it would sit in the shell history);
`--password-stdin` reads one line, for a script.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    ap.add_argument("--admin", default="gil")
    ap.add_argument("--name", default="")
    ap.add_argument("--password-stdin", action="store_true")
    args = ap.parse_args(argv)

    from assistant.users import migrate, passwords
    if args.dry_run:
        print(json.dumps(migrate.plan(), indent=2))
        return 0
    try:
        if args.rollback:
            back = migrate.rollback()
            print(f"rolled back: {len(back)} store(s) returned to the top level")
            return 0
        if args.password_stdin:
            pw = sys.stdin.readline().rstrip("\n")
        else:
            pw = getpass.getpass(f"password for the admin '{args.admin}': ")
            if pw != getpass.getpass("again: "):
                print("the two passwords differ — nothing was changed", file=sys.stderr)
                return 1
        if len(pw) < passwords.MIN_LENGTH:
            print(f"a password needs at least {passwords.MIN_LENGTH} characters", file=sys.stderr)
            return 1
        rec = migrate.apply(args.admin, pw, display_name=args.name)
    except migrate.MigrationError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(f"migrated {len(rec['moved'])} store(s) to users/{rec['admin']}/ — "
          f"backup at {rec['backup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
