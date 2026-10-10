class PlaybackError(Exception):
    """A user-safe failure message; never include tokens or signed links."""


class Cancelled(PlaybackError):
    pass
