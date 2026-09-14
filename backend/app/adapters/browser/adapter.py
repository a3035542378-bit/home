from app.adapters.browser.storage import EncryptedFileStorage

CAPABILITIES = {f"browser.{name}": True for name in (
    "navigation", "click", "fill", "text", "wait", "screenshot", "storage_state", "evaluate",
)}


class BrowserAdapter:
    def __init__(self, settings, *, storage=None, manager=None):
        if manager is None:
            from app.adapters.browser.manager import BrowserManager
            manager = BrowserManager(settings, storage or EncryptedFileStorage(
                settings.browser_state_dir, settings.browser_storage_key,
            ))
        self.manager = manager

    def capabilities(self):
        return dict(CAPABILITIES)

    async def start(self):
        await self.manager.startup()

    async def stop(self):
        await self.manager.shutdown()

    async def aclose(self):
        await self.stop()

    async def create_session(self, account_id, **options):
        return await self.manager.create_session(account_id, **options)

    def health(self):
        return self.manager.health()
