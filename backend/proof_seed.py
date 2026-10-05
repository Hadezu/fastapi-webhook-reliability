"""Seed synthetic operator and dedicated integration owner; no email is sent."""

from sqlmodel import Session

from app.core.db import engine, init_db
from app.core.security import get_password_hash
from app.models import User
from app.webhooks.config import config


def seed() -> None:
    with Session(engine) as session:
        init_db(session)
        owner_id = config().owner_id
        if session.get(User, owner_id) is None:
            import secrets

            session.add(
                User(
                    id=owner_id,
                    email="catalog-owner@example.com",
                    is_active=True,
                    hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                )
            )
            session.commit()


if __name__ == "__main__":
    seed()
