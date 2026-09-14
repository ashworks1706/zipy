"""The drive tool's schemas."""

from engine.tools.drive.schemas import SearchFilesParams
from engine.tools.drive.tool import DriveTool


def test_a_file_search_parses():
    assert SearchFilesParams(query="officer contact list").query == "officer contact list"


def test_drive_is_read_only():
    assert set(DriveTool.actions) == {"search_files", "list_folder"}
