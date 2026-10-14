class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class TransientError(Exception):
    """A failure that may succeed if the task is retried."""


class PermanentError(Exception):
    """A failure that should be dead-lettered without further retries."""


class CancelledError(Exception):
    """The owner cancelled the task while it was running."""


class LostLeaseError(Exception):
    """This worker no longer owns the task."""


def not_found(entity: str) -> AppError:
    return AppError("not_found", f"{entity} not found", 404)
