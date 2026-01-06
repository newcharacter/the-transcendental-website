"""Event logging for weather data replay and debugging.

Logs all weather observations and forecasts with timestamps
for later analysis and algorithm testing.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Iterator
import logging

from ..models.weather_data import WeatherObservation, SnowForecast, NowcastResult


logger = logging.getLogger(__name__)


class EventLogger:
    """Logs weather events to JSON files for replay.

    Events are stored in daily files:
    data/events/2026-01-06_observations.jsonl
    data/events/2026-01-06_forecasts.jsonl
    data/events/2026-01-06_nowcasts.jsonl
    """

    def __init__(self, event_dir: str = "data/events", retain_days: int = 30):
        self.event_dir = Path(event_dir)
        self.retain_days = retain_days
        self.event_dir.mkdir(parents=True, exist_ok=True)

    def log_observation(self, observation: WeatherObservation) -> None:
        """Log a weather observation."""
        self._append_event("observations", observation.model_dump(mode="json"))

    def log_observations(self, observations: list[WeatherObservation]) -> None:
        """Log multiple observations."""
        for obs in observations:
            self.log_observation(obs)

    def log_forecast(self, forecast: SnowForecast) -> None:
        """Log a snow forecast."""
        self._append_event("forecasts", forecast.model_dump(mode="json"))

    def log_nowcast(self, nowcast: NowcastResult) -> None:
        """Log a complete nowcast result."""
        self._append_event("nowcasts", nowcast.model_dump(mode="json"))

    def _append_event(self, event_type: str, data: dict) -> None:
        """Append event to daily log file."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = self.event_dir / f"{today}_{event_type}.jsonl"

        # Add metadata
        data["_logged_at"] = datetime.now(timezone.utc).isoformat()

        try:
            with open(filename, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to log event: {e}")

    def cleanup_old_events(self) -> int:
        """Remove event files older than retain_days.

        Returns:
            Number of files removed
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retain_days)
        removed = 0

        for filepath in self.event_dir.glob("*.jsonl"):
            try:
                # Parse date from filename
                date_str = filepath.stem.split("_")[0]
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                file_date = file_date.replace(tzinfo=timezone.utc)

                if file_date < cutoff:
                    filepath.unlink()
                    removed += 1
                    logger.info(f"Removed old event file: {filepath}")
            except Exception as e:
                logger.warning(f"Could not process {filepath}: {e}")

        return removed


def load_events(
    event_dir: str = "data/events",
    event_type: str = "observations",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Iterator[dict]:
    """Load events from log files for replay.

    Args:
        event_dir: Directory containing event files
        event_type: Type of events to load (observations, forecasts, nowcasts)
        start_date: Only load events after this date
        end_date: Only load events before this date

    Yields:
        Event dictionaries
    """
    event_path = Path(event_dir)

    if not event_path.exists():
        return

    # Find matching files
    for filepath in sorted(event_path.glob(f"*_{event_type}.jsonl")):
        try:
            # Parse date from filename
            date_str = filepath.stem.split("_")[0]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            file_date = file_date.replace(tzinfo=timezone.utc)

            # Check date range
            if start_date and file_date < start_date:
                continue
            if end_date and file_date > end_date:
                continue

            # Read events
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        yield json.loads(line)

        except Exception as e:
            logger.warning(f"Could not load {filepath}: {e}")
            continue


def replay_observations(
    event_dir: str = "data/events",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> list[WeatherObservation]:
    """Replay logged observations as WeatherObservation objects.

    Useful for testing algorithms against historical data.
    """
    observations = []

    for event_data in load_events(event_dir, "observations", start_date, end_date):
        # Remove logging metadata
        event_data.pop("_logged_at", None)
        try:
            obs = WeatherObservation(**event_data)
            observations.append(obs)
        except Exception as e:
            logger.warning(f"Could not parse observation: {e}")

    return observations
