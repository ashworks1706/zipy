"""The notion tool's schemas."""

from engine.tools.notion.schemas import CreatePageParams


def test_a_task_with_an_assignee_and_due_date_parses():
    params = CreatePageParams(
        database="Tasks",
        title="Design the flyer for the AI workshop",
        properties={"Assignee": "Maria", "Due": "2026-09-25"},
    )
    assert params.properties["Assignee"] == "Maria"
