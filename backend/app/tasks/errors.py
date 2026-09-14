from app.core.errors import BusinessError


class TaskBusinessError(BusinessError):
    def __init__(self, code="TASK_BUSINESS_FAILED", message="任务业务条件不成立"):
        super().__init__(code, message)


class TaskConfigError(TaskBusinessError):
    def __init__(self):
        super().__init__("TASK_CONFIG_INVALID", "任务配置无效")


class TaskPreconditionError(TaskBusinessError):
    pass


class TaskVerificationError(TaskBusinessError):
    def __init__(self):
        super().__init__("TASK_VERIFICATION_FAILED", "页面预期内容校验失败")


class TaskUserActionRequired(TaskBusinessError):
    def __init__(self):
        super().__init__("TASK_USER_ACTION_REQUIRED", "任务需要本人完成验证")
