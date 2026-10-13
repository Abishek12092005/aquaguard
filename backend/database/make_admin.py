"""Grant (or revoke) the admin role on an existing account.

WHY THIS IS NEEDED. The console is gated on the account's own `role` column --
`AdminRoute` on the client and `@admin_required` on the server both read it. That
column is written in exactly one place in the app: nowhere. Registration always
creates a plain user, so an installation that has never had SQL run against it by
hand has NO admin account and `/admin` is unreachable, which is what "the admin
page is not there" actually is.

This is the missing step: it flips `role` on an account that already exists.

TWO SEPARATE THINGS, DELIBERATELY. Being an admin gets you INTO the console
shell; the console's own username/password unlock (ADMIN_ACCESS_PASSWORD, see
services/admin_service.py) is what lets you ACT once inside. This script only
grants the first. It cannot and does not touch the console password.

Usage (from `backend/`, with the venv interpreter):

    # list every account, so you can see which email to promote
    python -m database.make_admin --list

    # promote an account
    python -m database.make_admin abishek@example.com

    # take the role away again
    python -m database.make_admin abishek@example.com --revoke

Reads DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD exactly like the app,
so it cannot be pointed somewhere the application is not.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

from app.config import BaseConfig


def _engine_uri(database: str | None) -> str:
    uri = BaseConfig.SQLALCHEMY_DATABASE_URI
    if not database:
        return uri
    base, _, query = uri.partition("?")
    prefix = base.rsplit("/", 1)[0]
    return f"{prefix}/{database}?{query}" if query else f"{prefix}/{database}"


def _list_accounts(engine) -> int:
    """Print every account with its current role, so a typo in an email is obvious."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, name, email, role FROM users ORDER BY id")
        ).all()

    if not rows:
        print("  No accounts exist yet. Register one through the app first.")
        return 0

    print(f"  {'id':>5}  {'role':<8}  email")
    for row in rows:
        print(f"  {row[0]:>5}  {row[3]:<8}  {row[2]}")
    return 0


def _verify_password(uri: str, email: str, password: str) -> int:
    """Confirm a plaintext password matches the account's stored hash (read-only)."""
    sql = "SELECT password_hash FROM users WHERE email = :email"
    engine = create_engine(uri)
    with engine.connect() as connection:
        row = connection.execute(text(sql), {"email": email}).first()
    from flask_bcrypt import Bcrypt

    if row is None or not row[0] or not Bcrypt().check_password_hash(row[0], password):
        print(f"  FAILED: password does not match for {email}.")
        return 1
    print(f"  Password verified for {email}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", nargs="?", help="The account to promote or demote.")
    parser.add_argument("--password", default=None, help="Verify this password matches the account's hash.")
    parser.add_argument("--list", action="store_true", help="List accounts and exit.")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Set the role back to 'user' instead of promoting to 'admin'.",
    )
    parser.add_argument("--database", default=None, help="Override the database name.")
    args = parser.parse_args()

    uri = _engine_uri(args.database)
    database = uri.split("?")[0].rsplit("/", 1)[1]
    print(f"Target database: {database}")

    if args.password:
        if not args.email:
            print("--password needs an email.")
            return 1
        return _verify_password(_engine_uri(args.database), args.email.strip(), args.password)

    engine = create_engine(uri)

    if args.list or not args.email:
        if not args.list and not args.email:
            print("Nothing to do: pass an email, or --list to see the accounts.")
        return _list_accounts(engine)

    role = "user" if args.revoke else "admin"
    email = args.email.strip()

    with engine.begin() as connection:
        result = connection.execute(
            text("UPDATE users SET role = :role WHERE email = :email"),
            {"role": role, "email": email},
        )
        if result.rowcount == 0:
            print(f"  No account with email {email!r}. Run with --list to see them.")
            return 1

    # Read back rather than trusting the statement: the role that matters is the
    # one in the table, not the one we asked for.
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT id, role FROM users WHERE email = :email"), {"email": email}
        ).first()

    if stored is None or stored[1] != role:
        print(f"  FAILED: {email} is not {role} after the update.")
        return 1

    print(f"  {email} (id {stored[0]}) is now role={stored[1]}.")
    if role == "admin":
        print(
            "  Sign in, open /admin, and unlock the console with the ADMIN_ACCESS_PASSWORD\n"
            "  username/password from the environment."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
