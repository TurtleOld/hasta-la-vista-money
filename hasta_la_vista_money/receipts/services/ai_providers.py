"""Shared exceptions for receipt image analysis clients."""


class RateLimitExceededError(Exception):
    """Exception raised when receipt analysis rate limit is exceeded."""


class ModelUnavailableError(Exception):
    """Exception raised when receipt analysis service is unavailable."""
