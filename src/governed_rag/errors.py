"""Errors. GragError and subclasses map to exit code 2."""


class GragError(Exception):
    """Usage, input or configuration error (exit code 2)."""


class PolicyError(GragError):
    """The access policy is invalid, or names an unknown user."""


class CorpusError(GragError):
    """A corpus file cannot be read or parsed."""
