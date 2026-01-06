# UK Weather Data Sources

Status of API access for the UK Snow Nowcast system.

## Currently Integrated

### Open-Meteo
- **Status**: ✅ Active (no key required)
- **URL**: https://api.open-meteo.com/v1/forecast
- **Data**: Snowfall forecasts, temperature, precipitation type
- **Update frequency**: 15 minutes
- **Limits**: 10,000 calls/day (fair use)
- **Models used**: ECMWF IFS, DWD ICON, MeteoFrance AROME

### Environment Agency Rainfall API
- **Status**: ✅ Active (no key required)
- **URL**: https://environment.data.gov.uk/flood-monitoring
- **Data**: Real-time rainfall from ~1000 UK rain gauges
- **Update frequency**: 15 minutes (more during floods)
- **Limits**: None (fair use expected)
- **License**: Open Government Licence

## Requires Registration

### Met Office Weather DataHub
- **Status**: ⏳ Registration required
- **URL**: https://datahub.metoffice.gov.uk/
- **Registration**: https://datahub.metoffice.gov.uk/
- **Free tier**: 360 calls/day
- **Data**: UKV model, site-specific forecasts, observations
- **Notes**: DataPoint retired December 2025, DataHub is replacement

To enable:
1. Register at https://datahub.metoffice.gov.uk/
2. Subscribe to free tier
3. Copy API key to config/settings.yaml under `data_sources.met_office_datahub.api_key`
4. Set `enabled: true`

## Crowdsourced (Optional)

### Twitter/X API
- **Status**: ⏳ Requires developer account
- **URL**: https://developer.twitter.com/
- **Cost**: Free tier available for basic search
- **Use case**: Real-time snow reports for validation

### NetWeather
- **Status**: ⏳ Commercial or subscription
- **URL**: https://www.netweather.tv/commercial/web
- **Cost**: From £10/month
- **Use case**: Forum scraping, radar data

## Not Yet Integrated

### CEDA MIDAS Open
- **URL**: https://catalogue.ceda.ac.uk/uuid/dbd451271eb04662beade68da43546e1/
- **Data**: Historical UK weather observations (not real-time)
- **Use case**: Algorithm training and validation

### Aviation METAR
- **URL**: Various (aviationweather.gov, etc.)
- **Data**: Hourly airport weather observations
- **Use case**: Additional ground truth validation

## API Registration Tracker

| Source | Status | API Key | Notes |
|--------|--------|---------|-------|
| Open-Meteo | ✅ Active | Not required | Working |
| Environment Agency | ✅ Active | Not required | Working |
| Met Office DataHub | ⏳ Pending | Required | Register at datahub.metoffice.gov.uk |
| Twitter | ⏳ Pending | Required | Apply for developer account |
| NetWeather | ❌ Not started | Required | Commercial - £10/month |
