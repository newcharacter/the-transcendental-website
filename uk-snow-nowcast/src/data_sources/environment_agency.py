"""Environment Agency real-time rainfall API integration.

Free API with no registration required. Provides data from ~1000
rain gauges across the UK.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from math import radians, cos, sin, asin, sqrt

from .base import DataSource, DataSourceConfig
from ..models.weather_data import (
    WeatherObservation,
    Location,
    PrecipitationType,
    DataQuality,
)


class EnvironmentAgencyConfig(DataSourceConfig):
    """Configuration for Environment Agency API."""
    base_url: str = "https://environment.data.gov.uk/flood-monitoring"
    update_interval_minutes: int = 15
    search_radius_km: float = 50.0


class EnvironmentAgencySource(DataSource):
    """Environment Agency real-time rainfall data source.

    Provides near real-time data from telemetry rain gauges across the UK.
    Data is updated every 15 minutes during normal conditions, more
    frequently during flood events.

    No API key required - open data under Open Government Licence.
    """

    def __init__(self, config: Optional[EnvironmentAgencyConfig] = None):
        if config is None:
            config = EnvironmentAgencyConfig()
        super().__init__(config)
        self._stations_cache: dict = {}

    @property
    def name(self) -> str:
        return "environment_agency"

    @property
    def requires_api_key(self) -> bool:
        return False

    async def fetch_observations(
        self, location: Location
    ) -> list[WeatherObservation]:
        """Fetch recent rainfall observations near location."""
        # First, find nearby stations
        stations = await self._find_nearby_stations(location)

        if not stations:
            return []

        # Fetch readings from nearby stations
        observations = []
        async with httpx.AsyncClient() as client:
            for station in stations[:10]:  # Limit to 10 nearest
                readings = await self._fetch_station_readings(client, station)
                observations.extend(readings)

        self._last_fetch = datetime.now(timezone.utc)
        self._cached_data = observations
        return observations

    async def fetch_forecast(
        self, location: Location, hours: int = 48
    ) -> list[WeatherObservation]:
        """Environment Agency doesn't provide forecasts.

        Returns empty list - use other sources for forecasts.
        """
        return []

    async def _find_nearby_stations(
        self, location: Location
    ) -> list[dict]:
        """Find rainfall monitoring stations near a location."""
        config = self.config
        assert isinstance(config, EnvironmentAgencyConfig)

        url = f"{config.base_url}/id/stations"
        params = {
            "parameter": "rainfall",
            "lat": location.latitude,
            "long": location.longitude,
            "dist": config.search_radius_km,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        stations = data.get("items", [])

        # Sort by distance and add distance to each station
        for station in stations:
            station_lat = station.get("lat", 0)
            station_lon = station.get("long", 0)
            station["distance_km"] = self._haversine_distance(
                location.latitude, location.longitude,
                station_lat, station_lon
            )

        stations.sort(key=lambda s: s.get("distance_km", float("inf")))

        # Cache stations
        self._stations_cache = {s["@id"]: s for s in stations}

        return stations

    async def _fetch_station_readings(
        self, client: httpx.AsyncClient, station: dict
    ) -> list[WeatherObservation]:
        """Fetch recent readings from a specific station."""
        station_id = station.get("@id", "")
        if not station_id:
            return []

        # Get readings from last 24 hours
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        url = f"{station_id}/readings"
        params = {
            "since": since,
            "_sorted": "true",
        }

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        readings = data.get("items", [])
        observations = []

        station_lat = station.get("lat", 0)
        station_lon = station.get("long", 0)
        station_location = Location(
            latitude=station_lat,
            longitude=station_lon,
            name=station.get("label", "Unknown"),
        )

        for reading in readings:
            try:
                timestamp_str = reading.get("dateTime", "")
                if not timestamp_str:
                    continue

                timestamp = datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                )

                # EA reports rainfall in mm (tipping bucket)
                value = reading.get("value", 0)

                obs = WeatherObservation(
                    timestamp=timestamp,
                    location=station_location,
                    source=self.name,
                    precipitation_mm=value,
                    precipitation_type=(
                        PrecipitationType.RAIN if value > 0
                        else PrecipitationType.NONE
                    ),
                    quality=DataQuality.HIGH,  # Direct measurement
                )
                observations.append(obs)
            except Exception:
                continue

        return observations

    async def get_stations_map_data(
        self, location: Location
    ) -> list[dict]:
        """Get station data formatted for map display."""
        stations = await self._find_nearby_stations(location)

        return [
            {
                "id": s.get("@id"),
                "name": s.get("label", "Unknown"),
                "lat": s.get("lat"),
                "lon": s.get("long"),
                "distance_km": s.get("distance_km"),
            }
            for s in stations
        ]

    async def health_check(self) -> bool:
        """Check if Environment Agency API is responding."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.config.base_url}/id/stations",
                    params={"_limit": 1}
                )
                return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _haversine_distance(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Calculate distance between two points in km."""
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))

        # Earth radius in km
        r = 6371

        return c * r
