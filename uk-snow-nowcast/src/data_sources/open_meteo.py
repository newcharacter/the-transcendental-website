"""Open-Meteo weather API integration.

Free API with no key required. Provides excellent snowfall forecasts
combining multiple weather models.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx

from .base import DataSource, DataSourceConfig
from ..models.weather_data import (
    WeatherObservation,
    Location,
    PrecipitationType,
    DataQuality,
)


class OpenMeteoConfig(DataSourceConfig):
    """Configuration for Open-Meteo API."""
    base_url: str = "https://api.open-meteo.com/v1/forecast"
    update_interval_minutes: int = 15


class OpenMeteoSource(DataSource):
    """Open-Meteo weather data source.

    Combines multiple high-resolution weather models including:
    - ECMWF IFS (European)
    - DWD ICON (German, good for Europe)
    - MeteoFrance AROME/ARPEGE
    - NOAA GFS/HRRR

    No API key required for non-commercial use.
    """

    def __init__(self, config: Optional[OpenMeteoConfig] = None):
        if config is None:
            config = OpenMeteoConfig()
        super().__init__(config)

    @property
    def name(self) -> str:
        return "open_meteo"

    @property
    def requires_api_key(self) -> bool:
        return False

    async def fetch_observations(
        self, location: Location
    ) -> list[WeatherObservation]:
        """Fetch current conditions from Open-Meteo."""
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "current": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "snowfall",
                "weather_code",
                "cloud_cover",
                "pressure_msl",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]),
            "timezone": "UTC",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(self.config.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        current = data.get("current", {})
        if not current:
            return []

        # Determine precipitation type
        precip_type = self._weather_code_to_precip_type(
            current.get("weather_code", 0)
        )

        obs = WeatherObservation(
            timestamp=datetime.fromisoformat(
                current["time"].replace("Z", "+00:00")
            ),
            location=location,
            source=self.name,
            temperature_c=current.get("temperature_2m"),
            feels_like_c=current.get("apparent_temperature"),
            precipitation_mm=current.get("precipitation"),
            precipitation_type=precip_type,
            snowfall_cm=current.get("snowfall"),
            humidity_percent=current.get("relative_humidity_2m"),
            pressure_hpa=current.get("pressure_msl"),
            cloud_cover_percent=current.get("cloud_cover"),
            wind_speed_kmh=current.get("wind_speed_10m"),
            wind_direction_deg=current.get("wind_direction_10m"),
            wind_gust_kmh=current.get("wind_gusts_10m"),
            quality=DataQuality.HIGH,
        )

        self._last_fetch = datetime.now(timezone.utc)
        self._cached_data = [obs]
        return [obs]

    async def fetch_forecast(
        self, location: Location, hours: int = 48
    ) -> list[WeatherObservation]:
        """Fetch hourly forecast from Open-Meteo."""
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "precipitation_probability",
                "rain",
                "snowfall",
                "snow_depth",
                "weather_code",
                "cloud_cover",
                "visibility",
                "pressure_msl",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]),
            "forecast_hours": hours,
            "timezone": "UTC",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(self.config.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        observations = []
        for i, time_str in enumerate(times):
            weather_code = hourly.get("weather_code", [None])[i]
            precip_type = self._weather_code_to_precip_type(weather_code)

            obs = WeatherObservation(
                timestamp=datetime.fromisoformat(
                    time_str.replace("Z", "+00:00")
                ),
                location=location,
                source=self.name,
                temperature_c=self._safe_get(hourly, "temperature_2m", i),
                feels_like_c=self._safe_get(hourly, "apparent_temperature", i),
                precipitation_mm=self._safe_get(hourly, "precipitation", i),
                precipitation_type=precip_type,
                snowfall_cm=self._safe_get(hourly, "snowfall", i),
                snow_depth_cm=self._safe_get(hourly, "snow_depth", i),
                humidity_percent=self._safe_get(hourly, "relative_humidity_2m", i),
                pressure_hpa=self._safe_get(hourly, "pressure_msl", i),
                cloud_cover_percent=self._safe_get(hourly, "cloud_cover", i),
                visibility_m=self._safe_get(hourly, "visibility", i),
                wind_speed_kmh=self._safe_get(hourly, "wind_speed_10m", i),
                wind_direction_deg=self._safe_get(hourly, "wind_direction_10m", i),
                wind_gust_kmh=self._safe_get(hourly, "wind_gusts_10m", i),
                quality=DataQuality.HIGH if i < 24 else DataQuality.MEDIUM,
            )
            observations.append(obs)

        self._last_fetch = datetime.now(timezone.utc)
        return observations

    async def health_check(self) -> bool:
        """Check if Open-Meteo API is responding."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    self.config.base_url,
                    params={
                        "latitude": 51.5,
                        "longitude": -0.1,
                        "current": "temperature_2m",
                    }
                )
                return response.status_code == 200
        except Exception:
            return False

    def _safe_get(self, data: dict, key: str, index: int):
        """Safely get value from hourly data array."""
        arr = data.get(key, [])
        if index < len(arr):
            return arr[index]
        return None

    def _weather_code_to_precip_type(self, code: Optional[int]) -> PrecipitationType:
        """Convert WMO weather code to precipitation type.

        See: https://open-meteo.com/en/docs#weathervariables
        """
        if code is None:
            return PrecipitationType.UNKNOWN

        # Snow codes
        if code in (71, 73, 75, 77, 85, 86):
            return PrecipitationType.SNOW

        # Sleet/freezing rain codes
        if code in (66, 67, 56, 57):
            return PrecipitationType.SLEET

        # Rain codes
        if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            return PrecipitationType.RAIN

        # Hail
        if code in (96, 99):
            return PrecipitationType.HAIL

        # Clear/cloudy (no precipitation)
        if code in (0, 1, 2, 3, 45, 48):
            return PrecipitationType.NONE

        return PrecipitationType.UNKNOWN
