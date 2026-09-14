import ipaddress
from urllib.parse import urlsplit


def validate_public_url(value):
    """配置语法校验；不等同于允许网络访问。真实页面规则未核验前不导航。"""
    if value is None or value == "":
        return None
    raw = value.get_secret_value() if hasattr(value, "get_secret_value") else value
    try:
        url = urlsplit(raw)
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query
                or url.fragment or url.port not in {None, 443} or "\\" in raw
                or any(ord(c) < 33 for c in raw)):
            raise ValueError()
        host = url.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.replace(".", "").isdigit():
                raise ValueError() from None
        else:
            if not address.is_global:
                raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("QQ Web URL 必须为无凭据、无查询参数的公共 HTTPS 地址") from None
    return value
