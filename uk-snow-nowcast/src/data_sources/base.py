"""Abstract base class for pluggable data sources.

New data sources can be added by implementing this interface.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from ..models.weather_data import WeatherObservation, Location


class DataSourceConfig(BaseModel):
    """Base configuration for data sources."""
    enabled: bool = True
    base_url: str
    update_interval_minutes: int = 15
    api_key: Optional[str] = None


class DataSource(ABC):
    """Abstract base class for weather data sources.

    Implement this interface to add new data sources without
    modifying core logic.
    """

    def __init__(self, config: DataSourceConfig):
        self.config = config
        self._last_fetch: Optional[datetime] = None
        self._cached_data: list[WeatherObservation] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this data source."""
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Whether this source requires an API key."""
        pass

    @abstractmethod
    async def fetch_observations(
        self, location: Location
    ) -> list[WeatherObservation]:
        """Fetch current observations for a location.

        Args:
            location: Geographic location to fetch data for

        Returns:
            List of WeatherObservation objects in standardised format
        """
        pass

    @abstractmethod
    async def fetch_forecast(
        self, location: Location, hours: int = 48
    ) -> list[WeatherObservation]:
        """Fetch forecast data for a location.

        Args:
            location: Geographic location
            hours: Number of hours to forecast

        Returns:
            List of WeatherObservation objects for future times
        """
        pass

    async def health_check(self) -> bool:
        """Check if the data source is available.

        Returns:
            True if source is responding, False otherwise
        """
        try:
            # Default implementation - override for specific checks
            return self.config.enabled
        except Exception:
            return False

    def is_stale(self) -> bool:
        """Check if cached data needs refreshing."""
        if self._last_fetch is None:
            return True
        from datetime import timedelta
        age = datetime.utcnow() - self._last_fetch
        return age > timedelta(minutes=self.config.update_interval_minutes)
