class IdempotencyConflictError(RuntimeError):
    pass


class RunExecutionFailedError(RuntimeError):
    """A Run reached a durable FAILED outcome; the Worker itself may continue."""


class StaleExecutorError(RuntimeError):
    """The worker no longer owns a live lease/generation for this Run."""


class BusinessProgressionBlockedError(RuntimeError):
    """Current durable limits prohibit starting or committing new business work."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    @property
    def failure_reason(self) -> str:
        return str(self)
