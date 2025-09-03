from typing import Optional
from .models import get_session, TtsUser


def ensure_dev_user() -> int:
    with get_session() as s:
        user = s.query(TtsUser).filter(TtsUser.platform == 'dev', TtsUser.platform_user_id == 'dev').first()
        if user:
            return user.id
        user = TtsUser(
            unified_user_id='dev',
            name='Developer',
            email='dev@local',
            avatar_url=None,
            platform='dev',
            platform_user_id='dev',
        )
        s.add(user)
        s.commit()
        return user.id


def get_current_user_id(auth_enabled: bool, request) -> int:
    if not auth_enabled:
        # 开发模式：固定开发者用户
        return ensure_dev_user()
    # TODO: 鉴权开启后的真实用户ID获取（占位）
    return ensure_dev_user()
