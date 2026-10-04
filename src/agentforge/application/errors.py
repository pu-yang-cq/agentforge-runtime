class IdempotencyConflictError(RuntimeError):
    pass


class RunExecutionFailedError(RuntimeError):
    """A Run reached a durable FAILED outcome; the Worker itself may continue."""


class StaleExecutorError(RuntimeError):
    """The worker no longer owns a live lease/generation for this Run."""
