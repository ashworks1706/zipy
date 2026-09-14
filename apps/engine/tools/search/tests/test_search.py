"""The search tool's schemas."""

from engine.tools.search.schemas import CampusOrgsParams


def test_a_campus_org_query_parses():
    assert CampusOrgsParams(keywords="AI robotics").keywords == "AI robotics"
