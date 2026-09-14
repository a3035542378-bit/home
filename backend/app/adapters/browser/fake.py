from app.adapters.browser.adapter import CAPABILITIES
from app.adapters.browser.exceptions import (
    BrowserActionTimeout,
    BrowserNavigationError,
    BrowserUserActionRequired,
)


class FakeBrowserPage:
    def __init__(self, mode):
        self.mode, self.closed, self.values = mode, False, {}

    async def goto(self, url):
        if self.mode == "navigation_error":
            raise BrowserNavigationError()
        if self.mode == "timeout":
            raise BrowserActionTimeout()
        if self.mode == "user_action":
            raise BrowserUserActionRequired()
        self.url = url
        return 200

    async def click(self, selector):
        if self.mode == "timeout":
            raise BrowserActionTimeout()

    async def fill(self, selector, value):
        self.values[selector] = value

    async def title(self):
        return "Browser fixture"

    async def exists(self, selector):
        return selector != "#missing"

    async def text(self, selector):
        return self.values.get(selector, "Mock")

    async def close(self):
        self.closed = True


class FakeBrowserSession:
    def __init__(self, account_id, mode):
        self.account_id, self.mode, self.closed = account_id, mode, False
        self.pages = []

    async def new_page(self):
        page = FakeBrowserPage(self.mode)
        self.pages.append(page)
        return page

    async def close(self):
        for page in self.pages:
            await page.close()
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class FakeBrowserAdapter:
    def __init__(self, mode="success"):
        self.mode, self.started, self.sessions = mode, False, []

    def capabilities(self):
        return dict(CAPABILITIES)

    def health(self):
        return "UP" if self.started else "DOWN"

    async def start(self):
        self.started = True

    async def create_session(self, account_id, **kwargs):
        session = FakeBrowserSession(account_id, self.mode)
        self.sessions.append(session)
        return session

    async def aclose(self):
        for session in self.sessions:
            await session.close()
        self.started = False

    stop = aclose
