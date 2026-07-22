class WatchError(RuntimeError):
    """base error for watch mode."""


class WatchAlreadyRunningError(WatchError):
    """raised when another watch process owns the watcher state."""


class WatchUnavailableError(WatchError):
    """raised when watch mode has no available approved source."""
