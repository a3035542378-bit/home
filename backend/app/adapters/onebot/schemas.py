from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)


class AdapterResponse(StrictModel):
    status: Literal["ok", "failed", "async"]
    retcode: int
    data: Any = None
    message: str = ""
    wording: str = ""


class LoginInfo(StrictModel):
    user_id: int = Field(gt=0)
    nickname: str


class OnlineStatus(StrictModel):
    online: bool
    good: bool


class VersionInfo(StrictModel):
    app_name: str
    app_version: str
    protocol_version: str


class FriendInfo(LoginInfo):
    remark: str = ""


class GroupInfo(StrictModel):
    group_id: int = Field(gt=0)
    group_name: str
    member_count: int | None = None
    max_member_count: int | None = None


class StrangerInfo(LoginInfo):
    sex: Literal["male", "female", "unknown"] = "unknown"
    age: int = Field(default=0, ge=0)


class MessageReceipt(StrictModel):
    message_id: int


class EmptyParams(StrictModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class GroupParams(EmptyParams):
    group_id: int = Field(gt=0)


class UserParams(EmptyParams):
    user_id: int = Field(gt=0)


class DeleteMessageParams(EmptyParams):
    message_id: int


class MessageSegment(StrictModel):
    type: str = Field(min_length=1)
    data: dict[str, Any]


class PrivateMessageParams(UserParams):
    message: str | list[MessageSegment]


class GroupMessageParams(GroupParams):
    message: str | list[MessageSegment]


INPUT_MODELS = {
    "get_status": EmptyParams, "get_login_info": EmptyParams, "get_version_info": EmptyParams,
    "get_friend_list": EmptyParams, "get_group_list": EmptyParams,
    "get_group_info": GroupParams, "get_stranger_info": UserParams,
    "send_private_msg": PrivateMessageParams, "send_group_msg": GroupMessageParams,
    "delete_msg": DeleteMessageParams,
}
