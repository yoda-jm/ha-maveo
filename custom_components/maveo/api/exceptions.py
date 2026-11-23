"""Errors raised by the Maveo cloud API."""


class MaveoError(Exception):
    """Base class for Maveo API errors."""


class AuthError(MaveoError):
    """The Maveo cloud rejected the credentials; the user must sign in again."""


class CloudError(MaveoError):
    """The Maveo cloud could not be reached or returned an unexpected error."""


class APIError(MaveoError):
    """A REST call failed. Messages never include request or response bodies."""
