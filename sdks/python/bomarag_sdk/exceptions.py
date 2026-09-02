"""BomaRAG SDK exceptions."""


class BomaRAGError(Exception):
    """Base exception for BomaRAG SDK."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(BomaRAGError):
    """Raised when API key is invalid or missing."""

    pass


class RateLimitError(BomaRAGError):
    """Raised when rate limit is exceeded."""

    pass


class NotFoundError(BomaRAGError):
    """Raised when a resource is not found."""

    pass


class ValidationError(BomaRAGError):
    """Raised when request validation fails."""

    pass


class ServerError(BomaRAGError):
    """Raised when server returns an error."""

    pass
