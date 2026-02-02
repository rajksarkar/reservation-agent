"""Custom exceptions for the reservation agent."""


class ReservationAgentError(Exception):
    """Base exception for all reservation agent errors."""

    pass


class ConfigurationError(ReservationAgentError):
    """Error in configuration."""

    pass


class PlatformError(ReservationAgentError):
    """Base error for platform-related issues."""

    def __init__(self, platform: str, message: str):
        self.platform = platform
        super().__init__(f"[{platform}] {message}")


class AuthenticationError(PlatformError):
    """Authentication failed or session expired."""

    pass


class SessionExpiredError(AuthenticationError):
    """Session has expired and needs re-authentication."""

    pass


class BookingError(PlatformError):
    """Error during booking attempt."""

    pass


class SlotUnavailableError(BookingError):
    """Requested slot is no longer available."""

    pass


class BookingConfirmationError(BookingError):
    """Could not confirm booking was successful."""

    pass


class RateLimitError(PlatformError):
    """Platform is rate limiting requests."""

    def __init__(self, platform: str, retry_after: int | None = None):
        self.retry_after = retry_after
        message = "Rate limited"
        if retry_after:
            message += f", retry after {retry_after}s"
        super().__init__(platform, message)


class CircuitBreakerOpenError(ReservationAgentError):
    """Circuit breaker is open, not allowing requests."""

    def __init__(self, platform: str, reset_time: float):
        self.platform = platform
        self.reset_time = reset_time
        super().__init__(f"Circuit breaker open for {platform}, resets at {reset_time}")


class BrowserError(ReservationAgentError):
    """Error with browser automation."""

    pass


class BrowserTimeoutError(BrowserError):
    """Browser operation timed out."""

    pass


class ElementNotFoundError(BrowserError):
    """Expected page element not found."""

    def __init__(self, selector: str, context: str | None = None):
        self.selector = selector
        self.context = context
        message = f"Element not found: {selector}"
        if context:
            message += f" ({context})"
        super().__init__(message)


class NotificationError(ReservationAgentError):
    """Error sending notification."""

    pass


class EmailDeliveryError(NotificationError):
    """Failed to deliver email notification."""

    pass


class DatabaseError(ReservationAgentError):
    """Database operation error."""

    pass
