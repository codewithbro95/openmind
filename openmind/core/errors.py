class SourceRemovalBlockedError(RuntimeError):
    """Raised when a source cannot be safely removed during active indexing."""
