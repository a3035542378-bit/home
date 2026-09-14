# 保留 Phase 3 导入兼容性。
from app.adapters.onebot.adapter import OneBotAdapter
from app.adapters.onebot.schemas import AdapterResponse as Envelope
from app.adapters.onebot.schemas import LoginInfo, OnlineStatus

__all__ = ["Envelope", "LoginInfo", "OneBotAdapter", "OnlineStatus"]
