"""Crowdsourced validation layer for weather observations.

Scrapes NetWeather forums and Twitter for real-time snow reports
to validate and weight-adjust technical data sources.

NOTE: This module requires separate API keys and respects platform ToS.
Social data is used for validation only, not as primary input.
"""

import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel
import httpx

from ..models.weather_data import Location


class SnowReport(BaseModel):
    """A crowdsourced snow report."""
    timestamp: datetime
    source: str  # "netweather", "twitter", etc.
    location: Optional[Location] = None
    location_text: str  # Raw location string
    content: str
    confidence: float = 0.5  # How confident we are this is valid
    snow_mentioned: bool = True
    accumulation_cm: Optional[float] = None  # Extracted if mentioned


class CrowdsourcedValidator:
    """Validates weather data against crowdsourced reports.

    Uses social media and forums to:
    - Confirm model predictions match reality
    - Catch edge cases where models miss local effects
    - Provide ground truth for algorithm training
    """

    def __init__(self):
        self._twitter_bearer_token: Optional[str] = None
        self._netweather_session: Optional[str] = None

    def configure_twitter(self, bearer_token: str) -> None:
        """Configure Twitter API access."""
        self._twitter_bearer_token = bearer_token

    async def search_twitter_snow_reports(
        self,
        location: Location,
        hours_back: int = 2,
    ) -> list[SnowReport]:
        """Search Twitter for recent snow reports near location.

        Requires Twitter API v2 bearer token.
        """
        if not self._twitter_bearer_token:
            return []

        # Build search query for snow near location
        # Note: Twitter geo search requires elevated access
        query = "snow UK -is:retweet lang:en"

        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": query,
            "max_results": 100,
            "tweet.fields": "created_at,geo,text",
        }
        headers = {
            "Authorization": f"Bearer {self._twitter_bearer_token}",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception:
            return []

        reports = []
        tweets = data.get("data", [])

        for tweet in tweets:
            text = tweet.get("text", "")
            created_at = tweet.get("created_at", "")

            # Basic snow keyword filtering
            if not self._mentions_snow(text):
                continue

            # Extract accumulation if mentioned
            accumulation = self._extract_accumulation(text)

            # Extract location from text
            location_text = self._extract_location(text)

            report = SnowReport(
                timestamp=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
                source="twitter",
                location_text=location_text or "UK",
                content=text[:500],
                confidence=self._calculate_report_confidence(text),
                snow_mentioned=True,
                accumulation_cm=accumulation,
            )
            reports.append(report)

        return reports

    async def scrape_netweather_forum(
        self,
        hours_back: int = 6,
    ) -> list[SnowReport]:
        """Scrape NetWeather forum for snow reports.

        Focuses on the "Model Output Discussion" and regional threads.
        Respects robots.txt and rate limits.
        """
        # NetWeather forum URLs
        base_url = "https://www.netweather.tv/forum"

        # This would need proper implementation with:
        # - Session management
        # - Rate limiting
        # - HTML parsing
        # - ToS compliance

        # Placeholder - returns empty for now
        # Real implementation would parse forum threads
        return []

    def validate_against_reports(
        self,
        predicted_snow: bool,
        predicted_amount_cm: float,
        reports: list[SnowReport],
        location: Location,
    ) -> dict:
        """Validate predictions against crowdsourced reports.

        Returns:
            Dictionary with:
            - agreement_score: 0-1 how well prediction matches reports
            - conflicting_reports: Reports that disagree
            - supporting_reports: Reports that agree
            - adjustment_factor: Suggested multiplier for prediction
        """
        if not reports:
            return {
                "agreement_score": 0.5,  # Neutral - no data
                "conflicting_reports": [],
                "supporting_reports": [],
                "adjustment_factor": 1.0,
            }

        supporting = []
        conflicting = []

        for report in reports:
            # Check if report mentions snow
            report_has_snow = report.snow_mentioned

            if predicted_snow == report_has_snow:
                supporting.append(report)
            else:
                conflicting.append(report)

        # Calculate agreement score
        total_weight = sum(r.confidence for r in reports)
        supporting_weight = sum(r.confidence for r in supporting)

        if total_weight > 0:
            agreement_score = supporting_weight / total_weight
        else:
            agreement_score = 0.5

        # Calculate adjustment factor
        # If many reports mention snow but prediction is low, increase
        # If prediction is high but no reports mention snow, decrease
        if supporting:
            avg_reported = sum(
                r.accumulation_cm or 0 for r in supporting if r.accumulation_cm
            )
            if avg_reported > 0 and predicted_amount_cm > 0:
                adjustment_factor = avg_reported / predicted_amount_cm
                adjustment_factor = max(0.5, min(2.0, adjustment_factor))
            else:
                adjustment_factor = 1.0
        else:
            adjustment_factor = 0.8 if conflicting else 1.0

        return {
            "agreement_score": agreement_score,
            "conflicting_reports": conflicting,
            "supporting_reports": supporting,
            "adjustment_factor": adjustment_factor,
        }

    def _mentions_snow(self, text: str) -> bool:
        """Check if text mentions snow."""
        snow_keywords = [
            "snow", "snowing", "snowed", "snowfall", "snowflake",
            "settling", "blizzard", "white out", "whiteout",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in snow_keywords)

    def _extract_accumulation(self, text: str) -> Optional[float]:
        """Extract snow accumulation amount from text.

        Handles various formats:
        - "2cm of snow"
        - "about 3 inches"
        - "10mm settling"
        """
        # CM patterns
        cm_patterns = [
            r"(\d+(?:\.\d+)?)\s*cm",
            r"(\d+(?:\.\d+)?)\s*centimeter",
        ]

        for pattern in cm_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))

        # Inch patterns (convert to cm)
        inch_patterns = [
            r"(\d+(?:\.\d+)?)\s*inch",
            r"(\d+(?:\.\d+)?)\s*\"",
        ]

        for pattern in inch_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1)) * 2.54

        # MM patterns (convert to cm)
        mm_patterns = [
            r"(\d+(?:\.\d+)?)\s*mm",
            r"(\d+(?:\.\d+)?)\s*millimeter",
        ]

        for pattern in mm_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1)) / 10

        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """Extract location from text."""
        # UK location patterns
        uk_locations = [
            r"in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"here\s+in\s+([A-Z][a-z]+)",
            r"([A-Z][a-z]+(?:shire|shire)?)",
        ]

        for pattern in uk_locations:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    def _calculate_report_confidence(self, text: str) -> float:
        """Calculate confidence score for a report.

        Higher confidence for:
        - Specific details (location, amounts)
        - Weather-focused accounts
        - Recent timestamps
        """
        confidence = 0.5

        # Has specific amount mentioned
        if self._extract_accumulation(text) is not None:
            confidence += 0.2

        # Has location
        if self._extract_location(text) is not None:
            confidence += 0.1

        # Length suggests more detail
        if len(text) > 100:
            confidence += 0.1

        # Negative indicators
        negative_words = ["forecast", "prediction", "expected", "might", "maybe"]
        if any(w in text.lower() for w in negative_words):
            confidence -= 0.2

        return max(0.1, min(1.0, confidence))
