"""Met Office Weather DataHub API integration.

Provides access to UK-specific high-resolution forecasts including
UKV model data. Requires free registration at datahub.metoffice.gov.uk.

Free tier: 360 calls/day
"""

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


class MetOfficeDataHubConfig(DataSourceConfig):
    """Configuration for Met Office DataHub API."""
    base_url: str = "https://data.hub.api.metoffice.gov.uk/sitespecific/v0"
    update_interval_minutes: int = 60  # Conservative due to 360/day limit
    api_key: str = ""


class MetOfficeDataHubSource(DataSource):
    """Met Office Weather DataHub data source.

    Provides site-specific forecasts from the Met Office, including
    data derived from the UKV high-resolution model.

    API docs: https://datahub.metoffice.gov.uk/docs
    """

    def __init__(self, config: MetOfficeDataHubConfig):
        super().__init__(config)
        if not config.api_key:
            raise ValueError("Met Office DataHub requires an API key")

    @property
    def name(self) -> str:
        return "met_office_datahub"

    @property
    def requires_api_key(self) -> bool:
        return True

    def _get_headers(self) -> dict:
        """Get headers with API key."""
        return {
            "apikey": self.config.api_key,
            "Accept": "application/json",
        }

    async def fetch_observations(
        self, location: Location
    ) -> list[WeatherObservation]:
        """Fetch current conditions from DataHub.

        Note: DataHub is primarily forecast-focused. For current conditions,
        we use the first timestep of the hourly forecast.
        """
        forecasts = await self.fetch_forecast(location, hours=1)
        return forecasts[:1] if forecasts else []

    async def fetch_forecast(
        self, location: Location, hours: int = 48
    ) -> list[WeatherObservation]:
        """Fetch hourly forecast from Met Office DataHub."""
        url = f"{self.config.base_url}/point/hourly"

        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "includeLocationName": "true",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

        observations = []

        # Parse the response
        features = data.get("features", [])
        if not features:
            return []

        feature = features[0]
        properties = feature.get("properties", {})
        timeseries = properties.get("timeSeries", [])

        # Get location name from response
        location_name = properties.get("location", {}).get("name", location.name)

        for i, timestep in enumerate(timeseries):
            if i >= hours:
                break

            try:
                time_str = timestep.get("time", "")
                if not time_str:
                    continue

                timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

                # Extract weather parameters (using actual Met Office field names)
                temp = timestep.get("screenTemperature")
                feels_like = timestep.get("feelsLikeTemperature")
                humidity = timestep.get("screenRelativeHumidity")
                wind_speed = timestep.get("windSpeed10m")  # m/s
                wind_dir = timestep.get("windDirectionFrom10m")
                wind_gust = timestep.get("windGustSpeed10m")  # m/s
                visibility = timestep.get("visibility")
                pressure = timestep.get("mslp")  # Already in hPa
                precip_rate = timestep.get("precipitationRate")  # mm/hr
                precip_amount = timestep.get("totalPrecipAmount")  # mm in hour
                snow_rate = timestep.get("totalSnowAmount")  # mm in hour
                weather_code = timestep.get("significantWeatherCode")

                # Convert units
                if wind_speed is not None:
                    wind_speed = wind_speed * 3.6  # m/s to km/h
                if wind_gust is not None:
                    wind_gust = wind_gust * 3.6
                # mslp is already in hPa, no conversion needed

                # Determine precipitation type from weather code
                precip_type = self._weather_code_to_precip_type(weather_code)

                # Convert snow from mm water equivalent to approximate cm
                snowfall_cm = None
                if snow_rate is not None and snow_rate > 0:
                    # Rough conversion: 1mm water = 1cm snow (varies with temp)
                    snowfall_cm = snow_rate

                obs = WeatherObservation(
                    timestamp=timestamp,
                    location=Location(
                        latitude=location.latitude,
                        longitude=location.longitude,
                        name=location_name,
                    ),
                    source=self.name,
                    temperature_c=temp,
                    feels_like_c=feels_like,
                    humidity_percent=humidity,
                    wind_speed_kmh=wind_speed,
                    wind_direction_deg=wind_dir,
                    wind_gust_kmh=wind_gust,
                    visibility_m=visibility,
                    pressure_hpa=pressure,
                    precipitation_mm=precip_amount,
                    precipitation_rate_mm_hr=precip_rate,
                    snowfall_cm=snowfall_cm,
                    precipitation_type=precip_type,
                    quality=DataQuality.HIGH,  # Official Met Office data
                )
                observations.append(obs)

            except Exception as e:
                continue

        self._last_fetch = datetime.now(timezone.utc)
        return observations

    async def health_check(self) -> bool:
        """Check if DataHub API is responding."""
        if not self.config.api_key:
            return False

        try:
            # Use a simple request to check connectivity
            url = f"{self.config.base_url}/point/hourly"
            params = {
                "latitude": 51.5,
                "longitude": -0.1,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                )
                return response.status_code == 200
        except Exception:
            return False

    def _weather_code_to_precip_type(self, code: Optional[int]) -> PrecipitationType:
        """Convert Met Office significant weather code to precipitation type.

        Met Office weather codes:
        https://datahub.metoffice.gov.uk/docs/glossary
        """
        if code is None:
            return PrecipitationType.UNKNOWN

        # Snow codes
        if code in (22, 23, 24, 25, 26, 27):  # Light/heavy snow, snow showers
            return PrecipitationType.SNOW

        # Sleet codes
        if code in (18, 19, 20, 21):  # Sleet
            return PrecipitationType.SLEET

        # Hail codes
        if code in (28, 29, 30):  # Hail
            return PrecipitationType.HAIL

        # Rain codes
        if code in (9, 10, 11, 12, 13, 14, 15, 16, 17):  # Rain, drizzle, showers
            return PrecipitationType.RAIN

        # No precipitation
        if code in (0, 1, 2, 3, 4, 5, 6, 7, 8):  # Clear, cloudy, fog, etc.
            return PrecipitationType.NONE

        return PrecipitationType.UNKNOWN
