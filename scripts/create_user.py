from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from web.auth import hash_password
from web.database import Database
from web.models import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a CNAgent login user.")
    parser.add_argument("username", help="Unique login name (1-64 characters).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    username = args.username.strip()
    if not 1 <= len(username) <= 64:
        print("Username must contain between 1 and 64 characters.")
        return 2

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 2
    if len(password) < 8:
        print("Password must contain at least 8 characters.")
        return 2

    database = Database(os.getenv("DATABASE_URL", "sqlite:///./cnagent.db"))
    database.create_tables()
    with database.session_factory() as session:
        existing = session.scalar(select(User).where(User.username == username))
        if existing is not None:
            print(f"User '{username}' already exists.")
            return 1
        session.add(User(username=username, password_hash=hash_password(password)))
        session.commit()

    print(f"Created user '{username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
