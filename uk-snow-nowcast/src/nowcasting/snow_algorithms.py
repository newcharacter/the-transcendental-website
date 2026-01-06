"""Snow-specific nowcasting algorithms.

Combines multiple data sources to produce short-term (1-2 hour)
snow forecasts with confidence intervals.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel

from ..models.weather_data import (
    WeatherObservation,
    SnowForecast,
    NowcastResult,
    Location,
    PrecipitationType,
)


class NowcastConfig(BaseModel):
    """Configuration for nowcasting algorithms."""
    # Temperature thresholds
    max_temp_for_snow: float = 2.0
    optimal_snow_temp_max: float = 0.5
    optimal_snow_temp_min: float = -5.0

    # Precipitation thresholds
    min_precipitation_rate: float = 0.1
    heavy_snow_rate: float = 2.0

    # Confidence weights
    temp_confidence_weight: float = 0.4
    precip_confidence_weight: float = 0.4
    observation_confidence_weight: float = 0.2

    # Time windows
    short_term_hours: int = 2
    medium_term_hours: int = 6

    # Algorithm weights
    persistence_weight: float = 0.3
    model_weight: float = 0.5
    observation_weight: float = 0.2


class SnowNowcaster:
    """Snow-specific nowcasting engine.

    Combines:
    - Model forecasts (Open-Meteo, Met Office)
    - Real-time observations (Environment Agency, weather stations)
    - Persistence (current conditions continuing)

    Accounts for:
    - Temperature gradients (snow vs rain threshold)
    - Radar detection limitations for snow
    - Local terrain effects
    """

    def __init__(self, config: Optional[NowcastConfig] = None):
        self.config = config or NowcastConfig()

    def generate_nowcast(
        self,
        location: Location,
        current_observations: list[WeatherObservation],
        forecasts: list[WeatherObservation],
    ) -> NowcastResult:
        """Generate a complete nowcast for a location.

        Args:
            location: Target location
            current_observations: Recent observations from all sources
            forecasts: Model forecasts from all sources

        Returns:
            NowcastResult with current conditions and hourly forecasts
        """
        now = datetime.now(timezone.utc)

        # Get current conditions summary
        current = self._summarise_current_conditions(current_observations)

        # Generate hourly snow forecasts for next 2 hours
        hourly_forecasts = []
        for hours_ahead in range(1, self.config.short_term_hours + 1):
            valid_time = now + timedelta(hours=hours_ahead)
            forecast = self._generate_hourly_forecast(
                location=location,
                valid_time=valid_time,
                current_observations=current_observations,
                model_forecasts=forecasts,
            )
            hourly_forecasts.append(forecast)

        # Calculate summary statistics
        snow_expected = any(f.probability_percent > 30 for f in hourly_forecasts)
        max_snowfall = max((f.snowfall_cm for f in hourly_forecasts), default=0)
        avg_confidence = (
            sum(f.confidence for f in hourly_forecasts) / len(hourly_forecasts)
            if hourly_forecasts else 0
        )

        # Track which sources contributed
        sources = set()
        for obs in current_observations:
            sources.add(obs.source)
        for fc in forecasts:
            sources.add(fc.source)

        return NowcastResult(
            location=location,
            generated_at=now,
            current=current,
            hourly_forecasts=hourly_forecasts,
            snow_expected=snow_expected,
            max_snowfall_cm=max_snowfall,
            overall_confidence=avg_confidence,
            sources_available=list(sources),
            sources_failed=[],
        )

    def _summarise_current_conditions(
        self, observations: list[WeatherObservation]
    ) -> Optional[WeatherObservation]:
        """Create a summary of current conditions from multiple sources."""
        if not observations:
            return None

        # Sort by timestamp, most recent first
        recent = sorted(
            observations,
            key=lambda o: o.timestamp,
            reverse=True
        )

        # Use most recent as base
        base = recent[0]

        # Average temperature from all sources
        temps = [o.temperature_c for o in recent if o.temperature_c is not None]
        if temps:
            base.temperature_c = sum(temps) / len(temps)

        return base

    def _generate_hourly_forecast(
        self,
        location: Location,
        valid_time: datetime,
        current_observations: list[WeatherObservation],
        model_forecasts: list[WeatherObservation],
    ) -> SnowForecast:
        """Generate snow forecast for a specific hour.

        Combines:
        - Persistence: Current snow conditions continuing
        - Model: Forecast from weather models
        - Observation: Recent observation trends
        """
        # Find relevant model forecasts for this hour
        relevant_forecasts = self._find_forecasts_for_time(
            model_forecasts, valid_time
        )

        # Calculate components
        persistence_snow = self._persistence_forecast(current_observations)
        model_snow = self._model_forecast(relevant_forecasts)
        observation_trend = self._observation_trend(current_observations)

        # Weighted combination
        cfg = self.config
        combined_snow = (
            cfg.persistence_weight * persistence_snow +
            cfg.model_weight * model_snow +
            cfg.observation_weight * observation_trend
        )

        # Get temperature for this time
        temp = None
        for fc in relevant_forecasts:
            if fc.temperature_c is not None:
                temp = fc.temperature_c
                break

        # Calculate confidence based on temperature
        temp_confidence = self._temperature_confidence(temp)
        model_confidence = 0.7 if relevant_forecasts else 0.3
        overall_confidence = (temp_confidence + model_confidence) / 2

        # Calculate probability of snow
        probability = self._snow_probability(temp, combined_snow, overall_confidence)

        # Determine precipitation type
        precip_type = self._determine_precip_type(temp, combined_snow)

        # Confidence bounds (wider = less confident)
        uncertainty = max(0.5, 1.0 - overall_confidence)
        snowfall_min = max(0, combined_snow * (1 - uncertainty))
        snowfall_max = combined_snow * (1 + uncertainty)

        # Track sources
        sources = list(set(fc.source for fc in relevant_forecasts))
        sources.extend(set(o.source for o in current_observations))

        return SnowForecast(
            valid_time=valid_time,
            location=location,
            generated_at=datetime.now(timezone.utc),
            snowfall_cm=combined_snow,
            snowfall_min_cm=snowfall_min,
            snowfall_max_cm=snowfall_max,
            probability_percent=probability,
            confidence=overall_confidence,
            temperature_c=temp,
            precipitation_type=precip_type,
            sources=list(set(sources)),
        )

    def _find_forecasts_for_time(
        self,
        forecasts: list[WeatherObservation],
        target_time: datetime,
    ) -> list[WeatherObservation]:
        """Find forecasts valid for a specific time."""
        tolerance = timedelta(minutes=30)
        return [
            fc for fc in forecasts
            if abs(fc.timestamp - target_time) <= tolerance
        ]

    def _persistence_forecast(
        self, observations: list[WeatherObservation]
    ) -> float:
        """Forecast based on current conditions persisting.

        Simple but surprisingly effective for short-term.
        """
        if not observations:
            return 0.0

        # Find most recent snowfall observation
        recent_snow = [
            o.snowfall_cm for o in observations
            if o.snowfall_cm is not None
        ]

        if recent_snow:
            return recent_snow[0]  # Most recent
        return 0.0

    def _model_forecast(
        self, forecasts: list[WeatherObservation]
    ) -> float:
        """Extract snow forecast from model data."""
        if not forecasts:
            return 0.0

        # Average snowfall from all model sources
        snow_values = [
            fc.snowfall_cm for fc in forecasts
            if fc.snowfall_cm is not None
        ]

        if snow_values:
            return sum(snow_values) / len(snow_values)
        return 0.0

    def _observation_trend(
        self, observations: list[WeatherObservation]
    ) -> float:
        """Calculate snowfall trend from recent observations.

        Extrapolates recent changes into the near future.
        """
        if len(observations) < 2:
            return 0.0

        # Sort by time
        sorted_obs = sorted(observations, key=lambda o: o.timestamp)

        # Get snowfall values with timestamps
        snow_obs = [
            (o.timestamp, o.snowfall_cm)
            for o in sorted_obs
            if o.snowfall_cm is not None
        ]

        if len(snow_obs) < 2:
            return 0.0

        # Simple linear trend
        first_time, first_snow = snow_obs[0]
        last_time, last_snow = snow_obs[-1]

        time_diff = (last_time - first_time).total_seconds() / 3600  # hours
        if time_diff <= 0:
            return last_snow

        snow_change_per_hour = (last_snow - first_snow) / time_diff

        # Extrapolate 1 hour ahead
        return last_snow + snow_change_per_hour

    def _temperature_confidence(self, temp: Optional[float]) -> float:
        """Calculate confidence based on temperature.

        Higher confidence when clearly snow (cold) or rain (warm).
        Lower confidence near the rain/snow threshold.
        """
        if temp is None:
            return 0.5  # Unknown

        cfg = self.config

        # Well below freezing - definitely snow if precipitating
        if temp < cfg.optimal_snow_temp_min:
            return 0.9

        # Optimal snow temperatures
        if cfg.optimal_snow_temp_min <= temp <= cfg.optimal_snow_temp_max:
            return 0.85

        # Marginal - could be snow or sleet
        if cfg.optimal_snow_temp_max < temp <= cfg.max_temp_for_snow:
            # Linear decrease in confidence
            range_size = cfg.max_temp_for_snow - cfg.optimal_snow_temp_max
            temp_in_range = temp - cfg.optimal_snow_temp_max
            return 0.85 - (0.4 * temp_in_range / range_size)

        # Too warm for snow
        if temp > cfg.max_temp_for_snow:
            return 0.9  # High confidence it's NOT snow

        return 0.5

    def _snow_probability(
        self, temp: Optional[float], snowfall: float, confidence: float
    ) -> float:
        """Calculate probability of snow occurring."""
        if temp is None:
            return 30.0 if snowfall > 0 else 0.0

        cfg = self.config

        # Too warm for snow
        if temp > cfg.max_temp_for_snow:
            return 0.0

        # No precipitation forecast
        if snowfall <= 0:
            return 0.0

        # Base probability from snowfall amount
        if snowfall >= cfg.heavy_snow_rate:
            base_prob = 90.0
        elif snowfall >= cfg.min_precipitation_rate:
            base_prob = 60.0
        else:
            base_prob = 30.0

        # Adjust for temperature (higher probability when colder)
        if temp <= cfg.optimal_snow_temp_min:
            temp_factor = 1.0
        elif temp <= cfg.optimal_snow_temp_max:
            temp_factor = 0.95
        else:
            # Linear decrease as we approach max_temp_for_snow
            range_size = cfg.max_temp_for_snow - cfg.optimal_snow_temp_max
            temp_in_range = temp - cfg.optimal_snow_temp_max
            temp_factor = 1.0 - (0.5 * temp_in_range / range_size)

        return min(100.0, base_prob * temp_factor * confidence)

    def _determine_precip_type(
        self, temp: Optional[float], snowfall: float
    ) -> PrecipitationType:
        """Determine precipitation type based on conditions."""
        if snowfall <= 0:
            return PrecipitationType.NONE

        if temp is None:
            return PrecipitationType.UNKNOWN

        cfg = self.config

        if temp <= cfg.optimal_snow_temp_max:
            return PrecipitationType.SNOW
        elif temp <= cfg.max_temp_for_snow:
            return PrecipitationType.SLEET
        else:
            return PrecipitationType.RAIN
