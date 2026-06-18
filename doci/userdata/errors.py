"""Errors shared by the user data services, mapped to HTTP codes in the routers."""


class UserDataError(Exception):
    """Base class for user-data-service errors."""


class NotFound(UserDataError):
    """A dossier / document / rule / knowledge entry does not exist (404)."""


class DuplicateKey(UserDataError):
    """A row with the same key already exists (409)."""
