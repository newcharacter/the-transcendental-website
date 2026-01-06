"""Standardised weather data models for the UK Snow Nowcast system.

All data sources convert their output to these formats for consistent processing.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class PrecipitationType(str, Enum):
    """Type of precipitation detected or forecast."""
    NONE = "none"
    RAIN = "rain"
    SLEET = "sleet"
    SNOW = "snow"
    FREEZING_RAIN = "freezing_rain"
    HAIL = "hail"
    UNKNOWN = "unknown"


class DataQuality(str, Enum):
    """Quality rating for data from various sources."""
    HIGH = "high"        # Direct observation or high-res model
    MEDIUM = "medium"    # Interpolated or lower-res model
    LOW = "low"          # Derived or uncertain
    UNKNOWN = "unknown"


class Location(BaseModel):
    """Geographic location with optional metadata."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    name: Optional[str] = None
    elevation_m: Optional[float] = None


class WeatherObservation(BaseModel):
    """Standardised weather observation from any data source.

    This is the core data structure that all sources convert to.
    """
    timestamp: datetime
    location: Location
    source: str  # e.g., "open_meteo", "environment_agency"

    # Temperature
    temperature_c: Optional[float] = None
    feels_like_c: Optional[float] = None
    dew_point_c: Optional[float] = None

    # Precipitation
    precipitation_mm: Optional[float] = None  # Total in period
    precipitation_rate_mm_hr: Optional[float] = None
    precipitation_type: PrecipitationType = PrecipitationType.UNKNOWN

    # Snow specific
    snowfall_cm: Optional[float] = None
    snow_depth_cm: Optional[float] = None

    # Wind
    wind_speed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_gust_kmh: Optional[float] = None

    # Humidity and pressure
    humidity_percent: Optional[float] = None
    pressure_hpa: Optional[float] = None

    # Visibility and cloud
    visibility_m: Optional[float] = None
    cloud_cover_percent: Optional[float] = None

    # Data quality
    quality: DataQuality = DataQuality.UNKNOWN

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SnowForecast(BaseModel):
    """Snow-specific forecast with confidence intervals.

    Used for nowcasting output.
    """
    valid_time: datetime
    location: Location
    generated_at: datetime

    # Snow predictions
    snowfall_cm: float = 0.0
    snowfall_min_cm: float = 0.0  # Lower confidence bound
    snowfall_max_cm: float = 0.0  # Upper confidence bound

    # Accumulation (total on ground)
    accumulation_cm: Optional[float] = None
    accumulation_min_cm: Optional[float] = None
    accumulation_max_cm: Optional[float] = None

    # Probability and confidence
    probability_percent: float = 0.0  # Chance of any snow
    confidence: float = 0.0  # 0-1 confidence in prediction

    # Supporting data
    temperature_c: Optional[float] = None
    precipitation_type: PrecipitationType = PrecipitationType.UNKNOWN

    # Attribution
    sources: list[str] = Field(default_factory=list)
    algorithm_version: str = "1.0"

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class NowcastResult(BaseModel):
    """Complete nowcast result for a location."""
    location: Location
    generated_at: datetime

    # Current conditions
    current: Optional[WeatherObservation] = None

    # Hourly forecasts (next 1-2 hours for nowcasting)
    hourly_forecasts: list[SnowForecast] = Field(default_factory=list)

    # Summary
    snow_expected: bool = False
    max_snowfall_cm: float = 0.0
    overall_confidence: float = 0.0

    # Data source health
    sources_available: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
