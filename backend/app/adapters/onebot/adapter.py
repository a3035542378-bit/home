from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.adapters.onebot.capability import CAPABILITIES
from app.adapters.onebot.exceptions import OneBotInvalidResponseError, OneBotNotConnectedError
from app.adapters.onebot.http_client import OneBotHttpClient
from app.adapters.onebot.schemas import (
    FriendInfo,
    GroupInfo,
    LoginInfo,
    MessageReceipt,
    OnlineStatus,
    StrangerInfo,
    VersionInfo,
)


class OneBotAdapter(OneBotHttpClient):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    def capabilities(self) -> dict[str, bool]:
        return dict(CAPABILITIES)

    async def _typed(self, action, model, params=None):
        envelope = await self.call(action, params)
        try:
            return TypeAdapter(model).validate_python(envelope.data, strict=True)
        except ValidationError:
            raise OneBotInvalidResponseError(action) from None

    async def get_status(self) -> OnlineStatus:
        return await self._typed("get_status", OnlineStatus)

    async def health_check(self) -> OnlineStatus:
        status = await self.get_status()
        if not status.online or not status.good:
            raise OneBotNotConnectedError("get_status")
        return status

    async def get_login_info(self) -> LoginInfo:
        await self.health_check()
        return await self._typed("get_login_info", LoginInfo)

    async def get_version_info(self) -> VersionInfo:
        return await self._typed("get_version_info", VersionInfo)

    async def get_friend_list(self) -> list[FriendInfo]:
        return await self._typed("get_friend_list", list[FriendInfo])

    async def get_group_list(self) -> list[GroupInfo]:
        return await self._typed("get_group_list", list[GroupInfo])

    async def get_group_info(self, group_id: int) -> GroupInfo:
        return await self._typed("get_group_info", GroupInfo, {"group_id": group_id})

    async def get_stranger_info(self, user_id: int) -> StrangerInfo:
        return await self._typed("get_stranger_info", StrangerInfo, {"user_id": user_id})

    async def send_private_msg(self, user_id: int, message: str | list[dict[str, Any]]) -> MessageReceipt:
        return await self._typed("send_private_msg", MessageReceipt,
                                 {"user_id": user_id, "message": message})

    async def send_group_msg(self, group_id: int, message: str | list[dict[str, Any]]) -> MessageReceipt:
        return await self._typed("send_group_msg", MessageReceipt,
                                 {"group_id": group_id, "message": message})

    async def delete_msg(self, message_id: int) -> None:
        response = await self.call("delete_msg", {"message_id": message_id})
        if response.data is not None and response.data != {}:
            raise OneBotInvalidResponseError("delete_msg")
