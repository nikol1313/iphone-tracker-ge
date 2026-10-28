from datetime import datetime


class ConflictError(Exception):
    pass


class NotFoundError(Exception):
    pass


class RefreshInProgressError(ConflictError):
    pass


class RefreshCooldownError(Exception):
    def __init__(self, available_at: datetime) -> None:
        super().__init__(f"Prices can be refreshed again at {available_at.isoformat()}")
        self.available_at = available_at


class EmptyScrapeError(Exception):
    """A scraper returned no products, which usually means the store markup changed."""
