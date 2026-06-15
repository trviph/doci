"""Errors shared by the user data services, mapped to HTTP codes in the router."""


class UserDataError(Exception):
    """Base class for user-data-service errors."""


class NotFound(UserDataError):
    """A group / rule / dataset / record does not exist (404)."""


class DuplicateKey(UserDataError):
    """A row with the same key already exists (409)."""


class SchemaViolation(UserDataError):
    """A reference record does not conform to its dataset's field schema (422)."""


class UnknownField(UserDataError):
    """A query filter references a field not declared in the dataset schema (400)."""
