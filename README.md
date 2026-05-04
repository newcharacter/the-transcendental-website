# the-transcendental-website

This repo currently holds two unrelated projects. They share no code; they're just colocated for convenience.

## 1. `index.html` — The Transcendental Motherfucking Website

A satirical homage to [motherfuckingwebsite.com](https://motherfuckingwebsite.com/) and [bettermotherfuckingwebsite.com](https://bettermotherfuckingwebsite.com/). Single-file HTML with a Solarized palette, light/dark via `prefers-color-scheme`, and a "no divs, no classes" CSS-grid layout.

To view locally, just open `index.html` in a browser.

## 2. `uk-snow-nowcast/` — UK Snow Nowcast

A Python project that fetches real-time UK weather data and produces short-term snow nowcasts via a Streamlit dashboard.

### Data sources
- **Open-Meteo** — snowfall forecasts, precipitation type (no key required)
- **Environment Agency Rainfall API** — real-time rainfall from ~1000 UK gauges (no key required)
- **Met Office Weather DataHub** — UKV model, site-specific forecasts (registration required)

See [`uk-snow-nowcast/API_SOURCES.md`](./uk-snow-nowcast/API_SOURCES.md) for the full list and registration status.

### Layout
```
uk-snow-nowcast/
  run.py                # CLI entry point (dashboard / test / fetch modes)
  config/settings.yaml  # location and source configuration
  dashboard/app.py      # Streamlit UI
  src/
    data_sources/       # Open-Meteo, Environment Agency, Met Office adapters
    models/             # Pydantic weather data models
    nowcasting/         # snow nowcast algorithms
    utils/              # logging
    validation/         # public weather scraper for cross-checks
  requirements.txt
```

### Quick start
```bash
cd uk-snow-nowcast
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the dashboard
streamlit run dashboard/app.py

# Or use the CLI runner
python run.py --test     # quick test of data sources
python run.py --fetch    # fetch and display current data
python run.py            # launch dashboard
```

## Note

These two projects probably want to live in separate repos eventually. For now they're sharing this one.
