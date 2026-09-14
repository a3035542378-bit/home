from dataclasses import dataclass
from enum import StrEnum


class ActionType(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class ActionMetadata:
    action_type: ActionType
    retryable: bool
    idempotent: bool


ACTIONS = {name: ActionMetadata(ActionType.READ, True, True) for name in (
    "get_status", "get_login_info", "get_version_info", "get_friend_list", "get_group_list",
    "get_group_info", "get_stranger_info",
)}
ACTIONS.update({name: ActionMetadata(ActionType.WRITE, False, False) for name in (
    "send_private_msg", "send_group_msg", "delete_msg",
)})
CAPABILITIES = {
    "login_info": True, "status": True, "version_info": True, "friend_list": True,
    "group_list": True, "group_info": True, "stranger_info": True,
    "private_message": True, "group_message": True, "delete_message": True,
    "qzone": False, "mobile": False, "mobile_automation": False,
}
