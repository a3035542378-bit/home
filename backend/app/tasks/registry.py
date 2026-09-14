import importlib
import inspect
import pkgutil
import re

from app.core.errors import BusinessError
from app.tasks.base import BaseTask


class TaskRegistry:
    def __init__(self):
        self._tasks: dict[str, type[BaseTask]] = {}

    def register(self, task: type[BaseTask]) -> type[BaseTask]:
        if not inspect.isclass(task) or not issubclass(task, BaseTask) or inspect.isabstract(task):
            raise BusinessError("INVALID_PLUGIN", "插件必须继承并实现 BaseTask")
        code = getattr(task, "task_code", "")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            raise BusinessError("INVALID_PLUGIN", "插件 task_code 格式无效")
        if not inspect.iscoroutinefunction(task.execute):
            raise BusinessError("INVALID_PLUGIN", "插件 execute 必须使用 async")
        if code in self._tasks:
            raise BusinessError("DUPLICATE_PLUGIN", "插件 task_code 重复")
        self._tasks[code] = task
        return task

    def get(self, task_code: str) -> type[BaseTask]:
        if task_code not in self._tasks:
            raise BusinessError("TASK_NOT_FOUND", "任务插件不存在", 404)
        return self._tasks[task_code]


registry = TaskRegistry()
register_task = registry.register


def load_builtin_tasks() -> None:
    # 只加载工程内受信任的插件目录，不接受请求参数指定模块路径。
    package = importlib.import_module("app.tasks.builtin")
    for module in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        importlib.import_module(module.name)

    package = importlib.import_module("app.tasks.plugins")
    for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module.name)
