"""The zoom tool's schemas."""

from engine.tools.zoom.schemas import LatestSummaryParams


def test_latest_summary_needs_no_topic():
    assert LatestSummaryParams().topic == ""
