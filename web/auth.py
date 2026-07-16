from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from sqlalchemy import select

from .models import User

SESSION_USER_KEY = "user_id"
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def find_user_by_username(request: Request, username: str) -> User | None:
    database = request.app.state.database
    with database.session_factory() as session:
        return session.scalar(select(User).where(User.username == username.strip()))


def current_user(request: Request) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not isinstance(user_id, int):
        return None

    database = request.app.state.database
    with database.session_factory() as session:
        user = session.get(User, user_id)

    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def sign_in(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def sign_out(request: Request) -> None:
    request.session.clear()
