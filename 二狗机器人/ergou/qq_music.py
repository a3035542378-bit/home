"""QQ 音乐公开曲目检索与点歌卡适配器。播放地址只用于本次发送。"""
import asyncio
import http.client
import json
import logging
import re
import secrets
import time
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from .bulletins import public_get
from .queries import ProviderError

LOG = logging.getLogger(__name__)
SEARCH = "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?"
PLAY = "https://u.y.qq.com/cgi-bin/musicu.fcg?"
LANDING = "https://c.y.qq.com/v8/playsong.html?"
MID = re.compile(r"[A-Za-z0-9]{14}")


class Artwork(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta" and fields.get("property") == "og:image":
            self.url = qq_url(fields.get("content"))


def qq_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    url = urlsplit(value)
    if (url.scheme not in ("https", "http") or not (url.hostname or "").endswith(".qq.com")
            or url.username or url.password or url.port or url.fragment):
        return None
    return urlunsplit(("https", url.netloc, url.path, url.query, ""))


def normalized(value):
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def find_track(rows, query):
    wanted = normalized(query)
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid, title, artist = (row.get(key) for key in ("mid", "name", "singer"))
        if (not isinstance(mid, str) or not MID.fullmatch(mid)
                or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (title, artist))):
            continue
        if wanted in (normalized(title), normalized(artist + title), normalized(title + artist)):
            return mid, title, artist
    return None


def audio_url(data, kind, mid):
    reply = data.get(kind, {})
    if reply.get("code") != 0:
        return None
    result = reply.get("data") or {}
    for row in result.get("midurlinfo") or []:
        if row.get("songmid") == mid and row.get("result") == 0 and row.get("purl"):
            for host in result.get("sip") or []:
                url = qq_url(urljoin(host, row["purl"]))
                if url:
                    return url
    return None


async def resolve(query, search_url):
    fallback = dict(kind="share", title=query, url=search_url, description="打开歌曲搜索结果")
    deadline = time.monotonic() + 8

    async def get(url):
        raw = await asyncio.to_thread(public_get, url, 512 * 1024,
                                      min(3, deadline - time.monotonic()), user_agent="Mozilla/5.0")
        return raw.decode("utf-8")

    try:
        result = json.loads(await get(SEARCH + urlencode(dict(key=query, format="json", platform="yqq.json",
                                                              inCharset="utf8", outCharset="utf-8"))))
        track = find_track(result["data"]["song"]["itemlist"], query)
        if not track:
            return fallback
        mid, title, artist = track
        page = LANDING + urlencode({"songmid": mid})
        fallback = dict(kind="share", title=title, url=page, description=f"{artist} · 打开 QQ 音乐收听")
        html = await get(page)
        cover = Artwork()
        cover.feed(html)
        params = dict(songmid=[mid], songtype=[0], uin="0", loginflag=0, platform="20",
                      guid=str(secrets.randbelow(10**10)))
        lookup = {"comm": dict(uin="0", format="json", ct=24, cv=0)}
        def request(options):
            return dict(module="vkey.GetVkeyServer", method="CgiGetVkey", param=options)
        lookup["full"] = request(params)
        file_info = re.search(r'"file"\s*:\s*(\{[^{}]{1,4096}\})', html)
        if file_info:
            info = json.loads(file_info[1])
            media = info.get("media_mid")
            if info.get("size_try") and isinstance(media, str) and MID.fullmatch(media):
                lookup["trial"] = request(dict(params, filename=["RS02" + media + ".mp3"]))
        result = json.loads(await get(PLAY + urlencode({"data": json.dumps(lookup, separators=(",", ":"))})))
        audio = audio_url(result, "full", mid) or audio_url(result, "trial", mid)
        if audio:
            card = dict(kind="music", title=title, author=artist, url=page, musicUrl=audio)
            if cover.url:
                card["thumbnailUrl"] = cover.url
            return card
    except (ProviderError, OSError, http.client.HTTPException, ValueError, KeyError, TypeError, AttributeError) as exc:
        LOG.info("QQ music lookup unavailable (%s)", type(exc).__name__)
    return fallback
