class IdempotencyConflictError(RuntimeError):
    pass


class RunExecutionFailedError(RuntimeError):
    """A Run reached a durable FAILED outcome; the Worker itself may continue."""


class StaleExecutorError(RuntimeError):
    """The worker no longer owns a live lease/generation for this Run."""


class ToolAdapterError(RuntimeError):
    """Structured adapter failure; unknown exceptions are never implicitly retryable."""

    def __init__(
        self,
        message: str,
        *,
        error_class: str,
        definite_not_executed: bool,
    ) -> None:
        self.error_class = error_class
        self.definite_not_executed = definite_not_executed
        super().__init__(message)


class ToolTransientError(ToolAdapterError):
    """Explicit opt-in signal for a retryable READ adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class SideEffectTransientError(ToolAdapterError):
    """Explicit retry signal only when the adapter proves no external effect occurred."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class BusinessProgressionBlockedError(RuntimeError):
    """Current durable limits prohibit starting or committing new business work."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    @property
    def failure_reason(self) -> str:
        return str(self)
