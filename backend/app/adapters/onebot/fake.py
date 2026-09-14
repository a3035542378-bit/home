from app.adapters.errors import AdapterTimeoutError
from app.adapters.onebot.adapter import OneBotAdapter
from app.adapters.onebot.exceptions import (
    OneBotApiError,
    OneBotAuthenticationError,
    OneBotConnectionError,
    OneBotInvalidResponseError,
    OneBotTimeoutError,
)
from app.adapters.onebot.schemas import AdapterResponse


class FakeOneBotAdapter(OneBotAdapter):
    """不建立网络连接，用于任务插件和 Service 测试。"""

    def __init__(
        self,
        mode="success",
        user_id=123456,
        *,
        online=True,
        good=True,
        friend_count=0,
        group_count=0,
    ):
        self.mode, self.user_id = mode, user_id
        self.calls = []
        self.metrics = {}
        self.online, self.good = online, good
        self.friend_count, self.group_count = friend_count, group_count

    async def aclose(self):
        return None

    async def call(self, action, params=None):
        self.calls.append((action, params))
        errors = {
            "auth": OneBotAuthenticationError,
            "connection": OneBotConnectionError,
            "timeout": OneBotTimeoutError,
            "api": OneBotApiError,
            "invalid": OneBotInvalidResponseError,
        }
        if self.mode in errors:
            raise errors[self.mode](action)
        if self.mode == "retryable_timeout":
            raise OneBotTimeoutError(action, retryable=True)
        if self.mode == "transient":
            raise AdapterTimeoutError()
        values = {
            "get_status": {
                "online": self.online and self.mode != "offline",
                "good": self.good and self.mode != "offline",
            },
            "get_login_info": {"user_id": self.user_id, "nickname": "Mock"},
            "get_version_info": {
                "app_name": "MockOneBot",
                "app_version": "1",
                "protocol_version": "v11",
            },
            "get_friend_list": [
                {
                    "user_id": 800000 + i,
                    "nickname": "friend-private",
                    "remark": "remark-private" if i % 2 else "",
                }
                for i in range(self.friend_count)
            ],
            "get_group_list": [
                {"group_id": 900000 + i, "group_name": "group-private"}
                for i in range(self.group_count)
            ],
            "get_group_info": {"group_id": (params or {}).get("group_id", 1), "group_name": "Mock"},
            "get_stranger_info": {"user_id": (params or {}).get("user_id", 1), "nickname": "Mock"},
            "send_private_msg": {"message_id": 1},
            "send_group_msg": {"message_id": 1},
            "delete_msg": None,
        }
        return AdapterResponse(status="ok", retcode=0, data=values.get(action))
