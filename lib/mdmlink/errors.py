class PlaybackError(Exception):
    """A user-safe failure message; never include tokens or signed links."""


class Cancelled(PlaybackError):
    pass


class SourceFailure(PlaybackError):
    """Only this explicit source-local failure permits automatic fallback."""


class SourcePreparing(PlaybackError):
    """A pending transfer/link must not trigger more automatic transfers."""


class AutoplayBudgetExpired(PlaybackError):
    """The whole automatic resolution sequence exhausted its budget."""
