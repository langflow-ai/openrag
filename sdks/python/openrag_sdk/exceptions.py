"""OpenRAG SDK exceptions."""


class OpenRAGError(Exception):
    """Base exception for OpenRAG SDK."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(OpenRAGError):
    """Raised when API key is invalid or missing."""

    pass


class RateLimitError(OpenRAGError):
    """Raised when rate limit is exceeded."""

    pass


class NotFoundError(OpenRAGError):
    """Raised when a resource is not found."""

    pass


class ValidationError(OpenRAGError):
    """Raised when request validation fails."""

    pass


class ServerError(OpenRAGError):
    """Raised when server returns an error."""

    pass
