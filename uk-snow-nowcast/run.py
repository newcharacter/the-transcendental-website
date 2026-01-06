#!/usr/bin/env python3
"""UK Snow Nowcast - Quick CLI runner.

Usage:
    python run.py              # Run dashboard
    python run.py --test       # Quick test of data sources
    python run.py --fetch      # Fetch and display current data
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))


async def test_data_sources():
    """Test all data sources are working."""
    from src.models.weather_data import Location
    from src.data_sources.open_meteo import OpenMeteoSource
    from src.data_sources.environment_agency import EnvironmentAgencySource

    # Default location (Canterbury, Kent)
    location = Location(
        latitude=51.2787,
        longitude=1.0803,
        name="Canterbury, Kent"
    )

    print(f"Testing data sources for {location.name}")
    print("=" * 50)

    # Test Open-Meteo
    print("\n[Open-Meteo]")
    try:
        source = OpenMeteoSource()
        healthy = await source.health_check()
        print(f"  Health check: {'✓' if healthy else '✗'}")

        if healthy:
            obs = await source.fetch_observations(location)
            print(f"  Current observations: {len(obs)}")
            if obs:
                print(f"    Temperature: {obs[0].temperature_c}°C")
                print(f"    Precipitation: {obs[0].precipitation_type.value}")
                if obs[0].snowfall_cm:
                    print(f"    Snowfall: {obs[0].snowfall_cm} cm")

            forecasts = await source.fetch_forecast(location, hours=6)
            print(f"  Forecast hours: {len(forecasts)}")
    except Exception as e:
        print(f"  Error: {e}")

    # Test Environment Agency
    print("\n[Environment Agency]")
    try:
        source = EnvironmentAgencySource()
        healthy = await source.health_check()
        print(f"  Health check: {'✓' if healthy else '✗'}")

        if healthy:
            obs = await source.fetch_observations(location)
            print(f"  Nearby stations with data: {len(obs)}")
            if obs:
                print(f"    Latest reading: {obs[0].precipitation_mm} mm")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n" + "=" * 50)
    print("Test complete!")


async def fetch_and_display():
    """Fetch current nowcast and display in terminal."""
    from src.models.weather_data import Location
    from src.data_sources.open_meteo import OpenMeteoSource
    from src.data_sources.environment_agency import EnvironmentAgencySource
    from src.nowcasting.snow_algorithms import SnowNowcaster

    location = Location(
        latitude=51.2787,
        longitude=1.0803,
        name="Canterbury, Kent"
    )

    print(f"UK Snow Nowcast - {location.name}")
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    # Fetch data
    observations = []
    forecasts = []

    try:
        open_meteo = OpenMeteoSource()
        obs = await open_meteo.fetch_observations(location)
        fc = await open_meteo.fetch_forecast(location, hours=6)
        observations.extend(obs)
        forecasts.extend(fc)
    except Exception as e:
        print(f"Warning: Open-Meteo failed: {e}")

    try:
        ea = EnvironmentAgencySource()
        obs = await ea.fetch_observations(location)
        observations.extend(obs)
    except Exception as e:
        print(f"Warning: Environment Agency failed: {e}")

    # Generate nowcast
    nowcaster = SnowNowcaster()
    result = nowcaster.generate_nowcast(
        location=location,
        current_observations=observations,
        forecasts=forecasts,
    )

    # Display results
    print("\n[NOWCAST SUMMARY]")
    print(f"  Snow Expected: {'YES' if result.snow_expected else 'No'}")
    print(f"  Max Snowfall:  {result.max_snowfall_cm:.1f} cm")
    print(f"  Confidence:    {result.overall_confidence * 100:.0f}%")

    if result.current:
        print("\n[CURRENT CONDITIONS]")
        c = result.current
        if c.temperature_c is not None:
            print(f"  Temperature:   {c.temperature_c:.1f}°C")
        print(f"  Precipitation: {c.precipitation_type.value}")
        if c.snowfall_cm:
            print(f"  Snowfall:      {c.snowfall_cm:.1f} cm")

    print("\n[HOURLY FORECAST]")
    for fc in result.hourly_forecasts:
        time_str = fc.valid_time.strftime("%H:%M")
        temp_str = f"{fc.temperature_c:.1f}°C" if fc.temperature_c else "N/A"
        print(
            f"  {time_str}: "
            f"Snow {fc.snowfall_cm:.1f}cm "
            f"({fc.probability_percent:.0f}% chance) "
            f"| {temp_str}"
        )

    print("\n[DATA SOURCES]")
    print(f"  Available: {', '.join(result.sources_available)}")
    if result.sources_failed:
        print(f"  Failed: {', '.join(result.sources_failed)}")


def run_dashboard():
    """Launch Streamlit dashboard."""
    import subprocess
    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run(["streamlit", "run", str(dashboard_path)])


def main():
    parser = argparse.ArgumentParser(description="UK Snow Nowcast")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test data source connections"
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch and display current nowcast in terminal"
    )
    args = parser.parse_args()

    if args.test:
        asyncio.run(test_data_sources())
    elif args.fetch:
        asyncio.run(fetch_and_display())
    else:
        run_dashboard()


if __name__ == "__main__":
    main()
