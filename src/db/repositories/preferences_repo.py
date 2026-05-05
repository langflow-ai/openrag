from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import UserPreferences


class PreferencesRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: str) -> Optional[UserPreferences]:
        return await self.session.get(UserPreferences, user_id)

    async def upsert(
        self,
        user_id: str,
        agent_system_prompt_override: Optional[str] = None,
        default_kf_id: Optional[str] = None,
        theme: Optional[str] = None,
        language: Optional[str] = None,
        provider_overrides: Optional[str] = None,
        preferences_json: Optional[str] = None,
    ) -> UserPreferences:
        prefs = await self.get(user_id)
        if prefs is None:
            prefs = UserPreferences(user_id=user_id)
        if agent_system_prompt_override is not None:
            prefs.agent_system_prompt_override = agent_system_prompt_override
        if default_kf_id is not None:
            prefs.default_kf_id = default_kf_id
        if theme is not None:
            prefs.theme = theme
        if language is not None:
            prefs.language = language
        if provider_overrides is not None:
            prefs.provider_overrides = provider_overrides
        if preferences_json is not None:
            prefs.preferences_json = preferences_json
        prefs.updated_at = datetime.utcnow()
        self.session.add(prefs)
        await self.session.flush()
        return prefs
