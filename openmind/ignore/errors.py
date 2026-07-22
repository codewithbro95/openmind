class IgnoreRuleError(ValueError):
    """base error for invalid ignore-rule operations."""


class IgnoreRuleNotFoundError(IgnoreRuleError):
    """raised when an ignore rule does not exist."""


class ProtectedIgnoreRuleError(IgnoreRuleError):
    """raised when a protected system rule would be changed."""


class DuplicateIgnoreRuleError(IgnoreRuleError):
    """raised when an equivalent ignore rule already exists."""
