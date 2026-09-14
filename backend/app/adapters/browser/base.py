from typing import Protocol


class SiteAdapter(Protocol):
    """网站自己定义认证规则；通用浏览器层不包含具体网站选择器。"""
    async def is_authenticated(self, session) -> bool: ...
