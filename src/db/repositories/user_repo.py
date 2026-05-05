from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.repositories._helpers import email_lookup_hash


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: str) -> Optional[User]:
        return await self.session.get(User, user_id)

    async def get_by_oauth(self, provider: str, subject: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(
                User.oauth_provider == provider, User.oauth_subject == subject
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        h = email_lookup_hash(email)
        if not h:
            return None
        result = await self.session.execute(
            select(User).where(User.email_lookup_hash == h)
        )
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[User]:
        result = await self.session.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def add(self, user: User) -> User:
        if user.email and not user.email_lookup_hash:
            user.email_lookup_hash = email_lookup_hash(user.email)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_last_login(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if user:
            user.last_login = datetime.utcnow()
            user.updated_at = datetime.utcnow()
            self.session.add(user)
            await self.session.flush()

    async def merge_legacy(
        self, legacy: User, real_provider: str, real_subject: str,
        email: Optional[str], display_name: Optional[str],
        picture_url: Optional[str],
    ) -> User:
        legacy.oauth_provider = real_provider
        legacy.oauth_subject = real_subject
        if email:
            legacy.email = email
            legacy.email_lookup_hash = email_lookup_hash(email)
        if display_name:
            legacy.display_name = display_name
        if picture_url:
            legacy.picture_url = picture_url
        legacy.last_login = datetime.utcnow()
        legacy.updated_at = datetime.utcnow()
        self.session.add(legacy)
        await self.session.flush()
        return legacy
