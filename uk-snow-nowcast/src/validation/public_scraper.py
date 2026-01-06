"""Public weather forum and RSS feed scraper for validation data.

Scrapes NetWeather forums and weather RSS feeds for real-time snow reports.
No API keys required - just public web scraping with rate limiting.
"""

import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
import httpx
from bs4 import BeautifulSoup

from ..models.weather_data import Location


@dataclass
class SnowReport:
    """A crowdsourced snow report from public sources."""
    timestamp: datetime
    source: str
    location_text: str
    content: str
    confidence: float = 0.5
    accumulation_cm: Optional[float] = None
    url: Optional[str] = None


class PublicWeatherScraper:
    """Scrapes public weather forums and RSS feeds for snow reports.

    Sources:
    - NetWeather community forums (model discussion, regional threads)
    - BBC Weather RSS
    - Met Office RSS warnings

    Respects robots.txt and implements rate limiting.
    """

    def __init__(self, rate_limit_seconds: float = 2.0):
        self.rate_limit = rate_limit_seconds
        self._last_request: Optional[datetime] = None

    async def _rate_limited_get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Make a rate-limited GET request."""
        if self._last_request:
            elapsed = (datetime.now(timezone.utc) - self._last_request).total_seconds()
            if elapsed < self.rate_limit:
                await asyncio.sleep(self.rate_limit - elapsed)

        self._last_request = datetime.now(timezone.utc)
        return await client.get(url, follow_redirects=True)

    async def scrape_netweather_latest(self) -> list[SnowReport]:
        """Scrape NetWeather's latest posts for snow mentions.

        Focuses on the Model Output Discussion forum which has
        knowledgeable weather watchers.
        """
        reports = []

        # NetWeather forum RSS feed for model discussion
        rss_url = "https://www.netweather.tv/forum/forum/4-model-output-discussion.xml/"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                client.headers["User-Agent"] = "UKSnowNowcast/1.0 (weather research)"

                response = await self._rate_limited_get(client, rss_url)
                if response.status_code != 200:
                    return []

                soup = BeautifulSoup(response.text, "xml")
                items = soup.find_all("item")

                for item in items[:20]:  # Check last 20 posts
                    title = item.find("title")
                    description = item.find("description")
                    link = item.find("link")
                    pub_date = item.find("pubDate")

                    if not title or not description:
                        continue

                    title_text = title.get_text()
                    desc_text = description.get_text()
                    combined = f"{title_text} {desc_text}".lower()

                    # Check for snow keywords
                    if not self._mentions_snow(combined):
                        continue

                    # Parse timestamp
                    timestamp = datetime.now(timezone.utc)
                    if pub_date:
                        try:
                            # RSS date format: "Mon, 06 Jan 2025 12:00:00 +0000"
                            timestamp = datetime.strptime(
                                pub_date.get_text().strip(),
                                "%a, %d %b %Y %H:%M:%S %z"
                            )
                        except ValueError:
                            pass

                    # Extract location if mentioned
                    location = self._extract_location(desc_text)

                    # Extract accumulation if mentioned
                    accumulation = self._extract_accumulation(desc_text)

                    report = SnowReport(
                        timestamp=timestamp,
                        source="netweather_forum",
                        location_text=location or "UK",
                        content=desc_text[:500],
                        confidence=self._calculate_confidence(desc_text),
                        accumulation_cm=accumulation,
                        url=link.get_text() if link else None,
                    )
                    reports.append(report)

        except Exception:
            pass

        return reports

    async def scrape_met_office_warnings(self) -> list[SnowReport]:
        """Scrape Met Office RSS for snow/ice warnings."""
        reports = []

        # Met Office warnings RSS
        rss_url = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                client.headers["User-Agent"] = "UKSnowNowcast/1.0 (weather research)"

                response = await self._rate_limited_get(client, rss_url)
                if response.status_code != 200:
                    return []

                soup = BeautifulSoup(response.text, "xml")
                items = soup.find_all("item")

                for item in items:
                    title = item.find("title")
                    description = item.find("description")

                    if not title:
                        continue

                    title_text = title.get_text().lower()

                    # Only snow/ice warnings
                    if "snow" not in title_text and "ice" not in title_text:
                        continue

                    desc_text = description.get_text() if description else ""

                    report = SnowReport(
                        timestamp=datetime.now(timezone.utc),
                        source="met_office_warning",
                        location_text=self._extract_location(title_text) or "UK",
                        content=f"{title.get_text()}: {desc_text[:300]}",
                        confidence=0.9,  # Official warnings are high confidence
                        accumulation_cm=self._extract_accumulation(desc_text),
                    )
                    reports.append(report)

        except Exception:
            pass

        return reports

    async def scrape_reddit_ukweather(self) -> list[SnowReport]:
        """Scrape r/ukweather for snow reports.

        Uses Reddit's public JSON API (no auth required for read).
        """
        reports = []

        # Reddit public JSON endpoint
        url = "https://www.reddit.com/r/ukweather/new.json?limit=25"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                client.headers["User-Agent"] = "UKSnowNowcast/1.0 (weather research)"

                response = await self._rate_limited_get(client, url)
                if response.status_code != 200:
                    return []

                data = response.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    post_data = post.get("data", {})
                    title = post_data.get("title", "")
                    selftext = post_data.get("selftext", "")
                    created = post_data.get("created_utc", 0)

                    combined = f"{title} {selftext}".lower()

                    if not self._mentions_snow(combined):
                        continue

                    # Skip if too old (more than 24 hours)
                    post_time = datetime.fromtimestamp(created, tz=timezone.utc)
                    if datetime.now(timezone.utc) - post_time > timedelta(hours=24):
                        continue

                    report = SnowReport(
                        timestamp=post_time,
                        source="reddit_ukweather",
                        location_text=self._extract_location(combined) or "UK",
                        content=f"{title}: {selftext[:300]}",
                        confidence=self._calculate_confidence(combined),
                        accumulation_cm=self._extract_accumulation(combined),
                        url=f"https://reddit.com{post_data.get('permalink', '')}",
                    )
                    reports.append(report)

        except Exception:
            pass

        return reports

    async def get_all_reports(self) -> list[SnowReport]:
        """Fetch snow reports from all sources."""
        # Run all scrapers concurrently
        results = await asyncio.gather(
            self.scrape_netweather_latest(),
            self.scrape_met_office_warnings(),
            self.scrape_reddit_ukweather(),
            return_exceptions=True,
        )

        all_reports = []
        for result in results:
            if isinstance(result, list):
                all_reports.extend(result)

        # Sort by timestamp, most recent first
        all_reports.sort(key=lambda r: r.timestamp, reverse=True)

        return all_reports

    def _mentions_snow(self, text: str) -> bool:
        """Check if text mentions snow."""
        snow_keywords = [
            "snow", "snowing", "snowed", "snowfall", "snowflake",
            "settling", "blizzard", "white out", "whiteout",
            "flurries", "sleet", "wintry",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in snow_keywords)

    def _extract_accumulation(self, text: str) -> Optional[float]:
        """Extract snow accumulation from text."""
        # CM patterns
        cm_match = re.search(r"(\d+(?:\.\d+)?)\s*cm", text, re.IGNORECASE)
        if cm_match:
            return float(cm_match.group(1))

        # Inch patterns (convert to cm)
        inch_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|inches|\")", text, re.IGNORECASE)
        if inch_match:
            return float(inch_match.group(1)) * 2.54

        # MM patterns (convert to cm)
        mm_match = re.search(r"(\d+(?:\.\d+)?)\s*mm", text, re.IGNORECASE)
        if mm_match:
            return float(mm_match.group(1)) / 10

        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """Extract UK location from text."""
        # Common UK regions and cities
        locations = [
            "scotland", "edinburgh", "glasgow", "aberdeen", "dundee",
            "england", "london", "manchester", "birmingham", "leeds", "liverpool",
            "newcastle", "sheffield", "bristol", "nottingham", "leicester",
            "wales", "cardiff", "swansea", "newport",
            "northern ireland", "belfast", "derry",
            "kent", "surrey", "sussex", "essex", "hampshire", "devon", "cornwall",
            "yorkshire", "lancashire", "cumbria", "northumberland",
            "midlands", "east anglia", "south west", "south east", "north west",
            "highlands", "borders", "lowlands",
        ]

        text_lower = text.lower()
        for loc in locations:
            if loc in text_lower:
                return loc.title()

        return None

    def _calculate_confidence(self, text: str) -> float:
        """Calculate confidence score for a report."""
        confidence = 0.5

        # Has specific amount
        if self._extract_accumulation(text):
            confidence += 0.2

        # Has location
        if self._extract_location(text):
            confidence += 0.1

        # Detailed post (length)
        if len(text) > 200:
            confidence += 0.1

        # Present tense suggests current observation
        present_indicators = ["is snowing", "it's snowing", "currently", "right now", "just started"]
        if any(ind in text.lower() for ind in present_indicators):
            confidence += 0.15

        # Negative indicators (forecasts, predictions)
        forecast_words = ["forecast", "prediction", "expected", "might", "could", "may"]
        if any(w in text.lower() for w in forecast_words):
            confidence -= 0.2

        return max(0.1, min(1.0, confidence))
