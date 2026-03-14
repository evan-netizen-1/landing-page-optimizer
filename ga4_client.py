"""
ga4_client.py — GA4 Data API client for reading landing page A/B test metrics.

Reads signup_cta_click events and page_view events segmented by the hg_variant
user property to compute click-through rate per variant.

Requires a GCP service account with Viewer access to the GA4 property.
"""

import os
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    Filter,
    FilterExpression,
)
from google.oauth2 import service_account

log = logging.getLogger("ga4_client")

PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "427786646")


def _get_client() -> BetaAnalyticsDataClient:
    """Create an authenticated GA4 Data API client."""
    sa_json = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "")

    if sa_json and Path(sa_json).is_file():
        # Path to a JSON key file
        credentials = service_account.Credentials.from_service_account_file(
            sa_json,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    elif sa_json:
        # Inline JSON (e.g. from GitHub Actions secret)
        info = json.loads(sa_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    else:
        raise RuntimeError(
            "GA4_SERVICE_ACCOUNT_JSON must be set to a file path or inline JSON"
        )

    return BetaAnalyticsDataClient(credentials=credentials)


def get_variant_metrics(start_date: str, end_date: str = None) -> dict:
    """Get page views and CTA clicks per variant for the /signup page.

    Args:
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string, defaults to today

    Returns:
        {
            "baseline": {"page_views": int, "cta_clicks": int, "ctr": float},
            "challenger": {"page_views": int, "cta_clicks": int, "ctr": float},
        }
    """
    if end_date is None:
        end_date = date.today().isoformat()

    client = _get_client()
    property_name = f"properties/{PROPERTY_ID}"

    # Query 1: Page views by variant
    page_views_by_variant = _query_event_by_variant(
        client, property_name, "page_view", start_date, end_date,
        page_path="/signup"
    )

    # Query 2: CTA clicks by variant
    cta_clicks_by_variant = _query_event_by_variant(
        client, property_name, "signup_cta_click", start_date, end_date
    )

    results = {}
    for variant in ["baseline", "challenger"]:
        pv = page_views_by_variant.get(variant, 0)
        clicks = cta_clicks_by_variant.get(variant, 0)
        ctr = clicks / pv if pv > 0 else 0.0
        results[variant] = {
            "page_views": pv,
            "cta_clicks": clicks,
            "ctr": ctr,
        }

    log.info(
        "GA4 metrics [%s to %s]: baseline=%d views/%d clicks (%.1f%%), "
        "challenger=%d views/%d clicks (%.1f%%)",
        start_date, end_date,
        results["baseline"]["page_views"], results["baseline"]["cta_clicks"],
        results["baseline"]["ctr"] * 100,
        results["challenger"]["page_views"], results["challenger"]["cta_clicks"],
        results["challenger"]["ctr"] * 100,
    )

    return results


def _query_event_by_variant(
    client, property_name: str, event_name: str,
    start_date: str, end_date: str,
    page_path: str = None,
) -> dict:
    """Query GA4 for event counts grouped by hg_variant user property.

    Returns: {"baseline": count, "challenger": count}
    """
    dimensions = [
        Dimension(name="customUser:hg_variant"),
    ]

    metrics = [
        Metric(name="eventCount"),
    ]

    # Filter by event name
    event_filter = FilterExpression(
        filter=Filter(
            field_name="eventName",
            string_filter=Filter.StringFilter(
                value=event_name,
                match_type=Filter.StringFilter.MatchType.EXACT,
            ),
        )
    )

    request = RunReportRequest(
        property=property_name,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=dimensions,
        metrics=metrics,
        dimension_filter=event_filter,
    )

    response = client.run_report(request)

    result = {}
    for row in response.rows:
        variant = row.dimension_values[0].value
        count = int(row.metric_values[0].value)
        if variant in ("baseline", "challenger"):
            result[variant] = count

    return result


def get_total_untagged_views(start_date: str, end_date: str = None) -> int:
    """Get total page views on /signup that have no hg_variant tag.

    Useful for monitoring how many visitors see the page before the
    ab-test.js script loads (or if it fails to load).
    """
    if end_date is None:
        end_date = date.today().isoformat()

    client = _get_client()
    property_name = f"properties/{PROPERTY_ID}"

    # Get all page views for /signup
    all_views = _query_event_by_variant(
        client, property_name, "page_view", start_date, end_date,
        page_path="/signup"
    )

    total_tagged = sum(all_views.values())

    # Query total page views without variant filter
    request = RunReportRequest(
        property=property_name,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="eventCount")],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(
                    value="page_view",
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )
        ),
    )

    response = client.run_report(request)
    total_all = 0
    for row in response.rows:
        if "/signup" in row.dimension_values[0].value:
            total_all += int(row.metric_values[0].value)

    return total_all - total_tagged
