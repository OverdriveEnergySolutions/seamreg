from pathlib import Path


def test_status_names_match():
    web = Path("web/src/status.ts").read_text()
    assert "returned" in web
