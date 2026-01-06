"""UK Snow Nowcast Dashboard

Local Streamlit dashboard for real-time snow nowcasting.

Run with: streamlit run dashboard/app.py
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.weather_data import Location, NowcastResult
from src.data_sources.open_meteo import OpenMeteoSource
from src.data_sources.environment_agency import EnvironmentAgencySource
from src.data_sources.met_office_datahub import MetOfficeDataHubSource, MetOfficeDataHubConfig
from src.nowcasting.snow_algorithms import SnowNowcaster, NowcastConfig
from src.utils.logging import EventLogger
from src.validation.public_scraper import PublicWeatherScraper


# Page config
st.set_page_config(
    page_title="UK Snow Nowcast",
    page_icon="❄️",
    layout="wide",
)


def load_config() -> dict:
    """Load configuration from yaml file."""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def get_location_from_config(config: dict) -> Location:
    """Get location from config or defaults."""
    loc_config = config.get("location", {})
    return Location(
        latitude=loc_config.get("latitude", 51.2787),
        longitude=loc_config.get("longitude", 1.0803),
        name=loc_config.get("name", "Canterbury, Kent"),
    )


async def fetch_all_data(location: Location, config: dict) -> dict:
    """Fetch data from all available sources."""
    results = {
        "observations": [],
        "forecasts": [],
        "sources_available": [],
        "sources_failed": [],
    }

    ds_config = config.get("data_sources", {})

    # Open-Meteo (always available, no key needed)
    try:
        open_meteo = OpenMeteoSource()
        observations = await open_meteo.fetch_observations(location)
        forecasts = await open_meteo.fetch_forecast(location, hours=24)
        results["observations"].extend(observations)
        results["forecasts"].extend(forecasts)
        results["sources_available"].append("open_meteo")
    except Exception as e:
        results["sources_failed"].append(f"open_meteo: {str(e)}")

    # Environment Agency
    try:
        ea = EnvironmentAgencySource()
        observations = await ea.fetch_observations(location)
        results["observations"].extend(observations)
        results["sources_available"].append("environment_agency")
    except Exception as e:
        results["sources_failed"].append(f"environment_agency: {str(e)}")

    # Met Office DataHub (if configured)
    mo_config = ds_config.get("met_office_datahub", {})
    if mo_config.get("enabled") and mo_config.get("api_key"):
        try:
            datahub_config = MetOfficeDataHubConfig(
                base_url=mo_config.get("base_url", "https://data.hub.api.metoffice.gov.uk/sitespecific/v0"),
                api_key=mo_config["api_key"],
                update_interval_minutes=mo_config.get("update_interval_minutes", 60),
            )
            datahub = MetOfficeDataHubSource(datahub_config)
            forecasts = await datahub.fetch_forecast(location, hours=24)
            results["forecasts"].extend(forecasts)
            results["sources_available"].append("met_office_datahub")
        except Exception as e:
            results["sources_failed"].append(f"met_office_datahub: {str(e)}")

    return results


def run_async(coro):
    """Run async code in Streamlit."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def render_current_conditions(nowcast: NowcastResult):
    """Render current conditions card."""
    st.subheader("Current Conditions")

    if nowcast.current:
        current = nowcast.current
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            temp = current.temperature_c
            if temp is not None:
                st.metric("Temperature", f"{temp:.1f}°C")
            else:
                st.metric("Temperature", "N/A")

        with col2:
            precip_type = current.precipitation_type.value.title()
            st.metric("Precipitation", precip_type)

        with col3:
            if current.snowfall_cm is not None and current.snowfall_cm > 0:
                st.metric("Current Snowfall", f"{current.snowfall_cm:.1f} cm")
            else:
                st.metric("Current Snowfall", "None")

        with col4:
            if current.wind_speed_kmh is not None:
                st.metric("Wind", f"{current.wind_speed_kmh:.0f} km/h")
            else:
                st.metric("Wind", "N/A")
    else:
        st.warning("No current conditions available")


def render_nowcast_summary(nowcast: NowcastResult):
    """Render nowcast summary."""
    st.subheader("Snow Nowcast (Next 2 Hours)")

    col1, col2, col3 = st.columns(3)

    with col1:
        if nowcast.snow_expected:
            st.error("⚠️ Snow Expected")
        else:
            st.success("✓ No Snow Expected")

    with col2:
        st.metric(
            "Max Snowfall",
            f"{nowcast.max_snowfall_cm:.1f} cm",
            help="Maximum predicted snowfall in next 2 hours"
        )

    with col3:
        confidence_pct = nowcast.overall_confidence * 100
        st.metric(
            "Confidence",
            f"{confidence_pct:.0f}%",
            help="Overall confidence in the prediction"
        )


def render_hourly_forecast(nowcast: NowcastResult):
    """Render hourly forecast chart."""
    st.subheader("Hourly Forecast")

    if not nowcast.hourly_forecasts:
        st.info("No hourly forecast data available")
        return

    # Build dataframe
    data = []
    for fc in nowcast.hourly_forecasts:
        data.append({
            "Time": fc.valid_time,
            "Snowfall (cm)": fc.snowfall_cm,
            "Min": fc.snowfall_min_cm,
            "Max": fc.snowfall_max_cm,
            "Probability (%)": fc.probability_percent,
            "Temperature (°C)": fc.temperature_c,
            "Confidence": fc.confidence,
        })

    df = pd.DataFrame(data)

    # Create chart with confidence intervals
    fig = go.Figure()

    # Confidence interval (shaded area)
    fig.add_trace(go.Scatter(
        x=df["Time"],
        y=df["Max"],
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=df["Time"],
        y=df["Min"],
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(135, 206, 235, 0.3)",
        name="Confidence Range",
    ))

    # Main snowfall line
    fig.add_trace(go.Scatter(
        x=df["Time"],
        y=df["Snowfall (cm)"],
        mode="lines+markers",
        name="Snowfall",
        line=dict(color="blue", width=2),
        marker=dict(size=8),
    ))

    # Temperature on secondary axis
    fig.add_trace(go.Scatter(
        x=df["Time"],
        y=df["Temperature (°C)"],
        mode="lines",
        name="Temperature",
        line=dict(color="red", dash="dash"),
        yaxis="y2",
    ))

    fig.update_layout(
        title="Snowfall Forecast with Temperature",
        xaxis_title="Time",
        yaxis_title="Snowfall (cm)",
        yaxis2=dict(
            title="Temperature (°C)",
            overlaying="y",
            side="right",
        ),
        hovermode="x unified",
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)

    # Probability chart
    fig_prob = px.bar(
        df,
        x="Time",
        y="Probability (%)",
        title="Snow Probability",
        color="Probability (%)",
        color_continuous_scale="Blues",
    )
    fig_prob.update_layout(height=250)
    st.plotly_chart(fig_prob, use_container_width=True)


def render_data_sources(nowcast: NowcastResult, fetch_results: dict):
    """Render data source status."""
    st.subheader("Data Sources")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Available:**")
        for source in nowcast.sources_available:
            st.write(f"✓ {source}")

    with col2:
        st.write("**Failed:**")
        if nowcast.sources_failed or fetch_results.get("sources_failed"):
            for source in fetch_results.get("sources_failed", []):
                st.write(f"✗ {source}")
        else:
            st.write("None")


def render_community_reports():
    """Render community snow reports from public sources."""
    st.subheader("Community Reports")

    with st.expander("View latest snow reports from forums & warnings", expanded=False):
        try:
            scraper = PublicWeatherScraper()
            reports = run_async(scraper.get_all_reports())

            if not reports:
                st.info("No recent snow reports found")
                return

            # Group by source
            by_source = {}
            for r in reports:
                if r.source not in by_source:
                    by_source[r.source] = []
                by_source[r.source].append(r)

            for source, source_reports in by_source.items():
                source_name = {
                    "met_office_warning": "Met Office Warnings",
                    "reddit_ukweather": "Reddit r/ukweather",
                    "netweather_forum": "NetWeather Forum",
                }.get(source, source)

                st.write(f"**{source_name}** ({len(source_reports)} reports)")

                for r in source_reports[:5]:  # Show max 5 per source
                    conf_pct = int(r.confidence * 100)
                    acc_str = f" | {r.accumulation_cm:.1f}cm" if r.accumulation_cm else ""
                    st.write(f"- {r.location_text}{acc_str} (conf: {conf_pct}%)")
                    st.caption(f"  {r.content[:100]}...")

                if len(source_reports) > 5:
                    st.caption(f"  ...and {len(source_reports) - 5} more")

        except Exception as e:
            st.warning(f"Could not fetch community reports: {e}")


def render_sidebar(config: dict) -> Location:
    """Render sidebar with settings."""
    st.sidebar.title("Settings")

    # Location input
    st.sidebar.subheader("Location")

    default_loc = config.get("location", {})

    lat = st.sidebar.number_input(
        "Latitude",
        value=default_loc.get("latitude", 51.2787),
        min_value=-90.0,
        max_value=90.0,
        format="%.4f",
    )

    lon = st.sidebar.number_input(
        "Longitude",
        value=default_loc.get("longitude", 1.0803),
        min_value=-180.0,
        max_value=180.0,
        format="%.4f",
    )

    name = st.sidebar.text_input(
        "Location Name",
        value=default_loc.get("name", "Canterbury, Kent"),
    )

    location = Location(latitude=lat, longitude=lon, name=name)

    # Quick location presets for UK
    st.sidebar.subheader("Quick Locations")
    presets = {
        "London": (51.5074, -0.1278),
        "Manchester": (53.4808, -2.2426),
        "Edinburgh": (55.9533, -3.1883),
        "Cardiff": (51.4816, -3.1791),
        "Belfast": (54.5973, -5.9301),
        "Canterbury": (51.2787, 1.0803),
    }

    preset = st.sidebar.selectbox(
        "Or select a city:",
        options=["Custom"] + list(presets.keys()),
    )

    if preset != "Custom" and preset in presets:
        lat, lon = presets[preset]
        location = Location(latitude=lat, longitude=lon, name=preset)
        st.sidebar.info(f"Using {preset}: {lat:.4f}, {lon:.4f}")

    # Refresh button
    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        st.cache_data.clear()
        st.rerun()

    # Last updated
    st.sidebar.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")

    return location


def main():
    """Main dashboard application."""
    st.title("❄️ UK Snow Nowcast")
    st.caption("Real-time snow forecasting for the next 1-2 hours")

    # Load config
    config = load_config()

    # Render sidebar and get location
    location = render_sidebar(config)

    # Show location
    st.info(f"📍 Showing forecast for: **{location.name}** ({location.latitude:.4f}, {location.longitude:.4f})")

    # Fetch data
    with st.spinner("Fetching weather data..."):
        try:
            fetch_results = run_async(fetch_all_data(location, config))
        except Exception as e:
            st.error(f"Error fetching data: {e}")
            return

    # Generate nowcast
    nowcaster = SnowNowcaster()
    nowcast = nowcaster.generate_nowcast(
        location=location,
        current_observations=fetch_results["observations"],
        forecasts=fetch_results["forecasts"],
    )

    # Log event
    try:
        logger = EventLogger()
        logger.log_nowcast(nowcast)
    except Exception:
        pass  # Non-critical

    # Render dashboard sections
    render_nowcast_summary(nowcast)
    st.divider()

    render_current_conditions(nowcast)
    st.divider()

    render_hourly_forecast(nowcast)
    st.divider()

    render_data_sources(nowcast, fetch_results)

    # Community reports section
    st.divider()
    render_community_reports()

    # Footer
    st.divider()
    sources_str = ", ".join(nowcast.sources_available) if nowcast.sources_available else "None"
    st.caption(
        f"Data sources: {sources_str} | "
        f"Generated: {nowcast.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )


if __name__ == "__main__":
    main()
