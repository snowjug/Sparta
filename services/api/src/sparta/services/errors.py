"""Service-level errors. The API layer maps each one to the standard error envelope and HTTP status."""


class ServiceError(Exception):
    code = "internal_error"
    status = 500

    def __init__(self, message: str, *, details: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ServiceError):
    code, status = "not_found", 404


class Forbidden(ServiceError):
    code, status = "forbidden", 403


class Unauthorized(ServiceError):
    code, status = "unauthorized", 401


class Conflict(ServiceError):
    code, status = "conflict", 409


class UnsupportedByProvider(ServiceError):
    """The active telephony provider cannot do this. The message explains why (shown to the owner)."""

    code, status = "unsupported_by_provider", 409


class InvalidInput(ServiceError):
    code, status = "validation_error", 422


class PayloadTooLarge(ServiceError):
    code, status = "payload_too_large", 413


class UnsupportedMedia(ServiceError):
    code, status = "unsupported_media_type", 415


class RateLimited(ServiceError):
    code, status = "rate_limited", 429

    def __init__(self, message: str, *, retry_after_s: int = 60) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class SttUnavailable(ServiceError):
    code, status = "stt_unavailable", 422


class ProviderUnavailableError(ServiceError):
    code, status = "provider_unavailable", 503
