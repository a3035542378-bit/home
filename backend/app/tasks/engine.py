import asyncio
import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.adapters.browser.exceptions import BrowserUserActionRequired
from app.adapters.errors import AdapterError
from app.adapters.registry import AdapterRegistry
from app.core.errors import BusinessError
from app.models.common import ExecutionStatus, TriggerType, utcnow
from app.services.task_runtime import TaskStore
from app.tasks.base import TaskResult
from app.tasks.errors import TaskConfigError
from app.tasks.registry import TaskRegistry, registry

logger = logging.getLogger("app.task")
SKIP_CODES = {"TASK_DISABLED", "ACCOUNT_DISABLED", "DUPLICATE_EXECUTION"}


class TaskEngine:
    def __init__(
        self,
        store: TaskStore,
        task_registry: TaskRegistry = registry,
        adapters: Mapping[str, Any] | None = None,
        timeout_seconds: float = 60,
        adapter_provider=None,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self.store = store
        self.registry = task_registry
        self.adapters = dict(adapters or {})
        self.timeout = timeout_seconds
        self.adapter_provider = adapter_provider

    async def execute(
        self,
        account_id: int,
        task_code: str,
        trigger_type: TriggerType = TriggerType.MANUAL,
    ) -> TaskResult:
        start = utcnow()
        execution_id = str(uuid4())
        claimed = False

        def failure(code, message):
            return TaskResult(
                success=False,
                status=ExecutionStatus.SKIPPED if code in SKIP_CODES else ExecutionStatus.FAILED,
                message=message,
                error_code=code,
                start_time=start,
                end_time=utcnow(),
                execution_id=execution_id if claimed else None,
            )

        def log(status):
            logger.info(
                "task_execution",
                extra={
                    "event": "task_execution",
                    "execution_id": execution_id,
                    "account_id": account_id,
                    "task_code": task_code,
                    "status": status,
                },
            )

        try:
            self.registry.get(task_code)
            context = await self.store.begin(
                account_id, task_code, execution_id, trigger_type, start
            )
            claimed = True
            log(ExecutionStatus.RUNNING)
            result = await self.run(task_code, context)
            # 再次校验可变 data，执行时间和关联 ID 由引擎统一赋值。
            result = TaskResult.model_validate(
                {
                    **result.model_dump(),
                    "start_time": start,
                    "end_time": utcnow(),
                    "execution_id": execution_id,
                }
            )
            result.model_dump_json()
        except asyncio.CancelledError:
            log("CANCELLED")
            if claimed:
                await asyncio.shield(
                    self.store.finish(
                        account_id,
                        task_code,
                        execution_id,
                        failure("EXECUTION_CANCELLED", "执行被取消，请核对外部状态后再操作"),
                    )
                )
            raise
        except TimeoutError:
            result = failure("TASK_TIMEOUT", "执行超时，请核对外部状态后再操作")
        except AdapterError as exc:
            result = failure(exc.code, exc.message)
        except BusinessError as exc:
            result = failure(exc.code, exc.message)
        except Exception:  # noqa: BLE001 - 插件隔离边界，禁止记录第三方异常原文
            result = failure("TASK_EXCEPTION", "任务执行异常")
        log(result.status)
        if claimed:
            try:
                await self.store.finish(account_id, task_code, execution_id, result)
            except Exception:  # noqa: BLE001 - 持久化失败时不能宣称已记录成功
                log("PERSISTENCE_ERROR")
                result = failure(
                    "PERSISTENCE_ERROR", "结果保存失败，请核对执行状态，勿直接重复执行"
                )
        return result

    async def run(self, task_code, context):
        """执行已由 Worker 领取的上下文，不创建第二条执行记录。"""
        start = utcnow()
        context = replace(
            context, task_code=task_code, browser_evidence=[], progress={"stage": "CONFIG"}
        )
        task_class = None
        retryable = False
        try:
            task_class = self.registry.get(task_code)
            if task_class.config_schema:
                try:
                    config = task_class.config_schema.model_validate(dict(context.config))
                except ValidationError:
                    raise TaskConfigError() from None
                context = replace(context, validated_config=config)
            context = replace(context, onebot_worker_retry=task_class.onebot_worker_retry,
                              onebot_status_only=task_class.onebot_status_only)
            context.set_stage(
                "ONEBOT" if "onebot" in task_class.required_capabilities else "BROWSER"
            )
            async with (
                asyncio.timeout(min(self.timeout, task_class.timeout_seconds)),
                AsyncExitStack() as stack,
            ):
                adapters = {**self.adapters, **context.adapters}
                if self.adapter_provider:
                    services_factory = getattr(self.adapter_provider, "services_for_context", None)
                    if services_factory is not None:
                        services = services_factory(context)
                        if isinstance(services, Mapping):
                            context = replace(context, services={**context.services, **services})
                    supplied = await stack.enter_async_context(
                        self.adapter_provider.for_context(
                            context, task_class.required_capabilities
                        ),
                    )
                    adapters.update(supplied)
                for name, capabilities in task_class.required_capabilities.items():
                    context.set_stage(name.upper())
                    AdapterRegistry(adapters).require({name: capabilities})
                result = await task_class().execute(replace(context, adapters=adapters))
            if not isinstance(result, TaskResult):
                raise BusinessError("INVALID_TASK_RESULT", "插件未返回 TaskResult")
            result = TaskResult.model_validate(
                {
                    **result.model_dump(),
                    "data": {
                        **result.data,
                        **(
                            {"browser_evidence": context.browser_evidence}
                            if context.browser_evidence
                            else {}
                        ),
                    },
                    "task_version": task_class.task_version,
                    "plugin_version": task_class.plugin_version,
                    "retryable": False,
                    "execution_id": context.execution_id,
                    "start_time": start,
                    "end_time": utcnow(),
                }
            )
            result.model_dump_json()
            self.log_result(context, result, start)
            return result
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            code, message = "TASK_TIMEOUT", "任务超时，请核对外部状态"
        except AdapterError as exc:
            code, message = exc.code, exc.message
            retryable = bool(
                task_class
                and task_class.idempotent
                and task_class.read_only
                and task_class.retry_policy
                and code in task_class.retry_policy
                and getattr(exc, "retryable", False)
            )
        except BusinessError as exc:
            code, message = exc.code, exc.message
        except Exception:  # noqa: BLE001 - 插件隔离边界
            code, message = "TASK_EXCEPTION", "任务执行异常"
        if task_class:
            code = task_class.error_code_aliases.get(code, code)
        status = (
            ExecutionStatus.NEED_USER_ACTION
            if code in {BrowserUserActionRequired.code, "TASK_USER_ACTION_REQUIRED"}
            else ExecutionStatus.FAILED
        )
        result = TaskResult(
            success=False,
            status=status,
            error_code=code,
            failed_stage=context.progress.get("stage"),
            retryable=retryable,
            task_version=task_class.task_version if task_class else "unknown",
            plugin_version=task_class.plugin_version if task_class else "unknown",
            data={"browser_evidence": context.browser_evidence} if context.browser_evidence else {},
            message=message,
            execution_id=context.execution_id,
            start_time=start,
            end_time=utcnow(),
        )

        self.log_result(context, result, start)
        return result

    @staticmethod
    def log_result(context, result, start):
        logger.info(
            "task_completed",
            extra={
                "event": "task_completed",
                "execution_id": context.execution_id,
                "account_id": context.account.id,
                "task_code": context.task_code,
                "stage": context.progress.get("stage"),
                "status": result.status,
                "duration": (utcnow() - start).total_seconds(),
            },
        )
