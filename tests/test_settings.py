"""The saved settings file, seams.settings.json: what the checker accepts and how it names a mistake."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from seams import check, cli

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path, settings=None):
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": []}))
    if settings is not None:
        text = settings if isinstance(settings, str) else json.dumps(settings)
        (tmp_path / "seams.settings.json").write_text(text)
    return tmp_path


def test_preset_name_alone_passes(tmp_path):
    assert check.settings_errors(_repo(tmp_path, {"schema_version": 1, "preset": "standard"})) == []


def test_no_settings_file_means_no_settings_errors(tmp_path):
    assert check.settings_errors(_repo(tmp_path)) == []


def test_a_changed_step_setting_passes(tmp_path):
    data = {"schema_version": 1, "preset": "all-in",
            "changes": {"lead_check": {"effort": "xhigh"}, "review": {"model": "opus"}},
            "diff_limit_percent": 25}
    assert check.settings_errors(_repo(tmp_path, data)) == []


def test_misspelled_step_names_the_file_and_the_key(tmp_path):
    data = {"schema_version": 1, "preset": "standard", "changes": {"lead_chek": {"effort": "high"}}}
    errors = check.settings_errors(_repo(tmp_path, data))
    assert errors == ["seams.settings.json.changes: unknown field 'lead_chek'"]


def test_bad_effort_names_the_allowed_values(tmp_path):
    data = {"schema_version": 1, "preset": "standard", "changes": {"review": {"effort": "extreme"}}}
    [error] = check.settings_errors(_repo(tmp_path, data))
    assert error.startswith("seams.settings.json.changes.review.effort: must be one of low, medium, high")
    assert '"extreme"' in error


def test_unknown_preset_fails(tmp_path):
    [error] = check.settings_errors(_repo(tmp_path, {"schema_version": 1, "preset": "cheap"}))
    assert "seams.settings.json.preset: must be one of standard, all-in" in error


def test_broken_json_is_reported_not_raised(tmp_path):
    [error] = check.settings_errors(_repo(tmp_path, "{not json"))
    assert error.startswith("seams.settings.json: not valid JSON")


def test_seams_check_fails_on_a_bad_settings_file(tmp_path, capsys):
    repo = _repo(tmp_path, {"schema_version": 1, "preset": "standard", "changes": {"review": {"efort": "max"}}})
    assert check.main(["--root", str(repo)]) == 1
    assert "unknown field 'efort'" in capsys.readouterr().out


def test_settings_never_enter_the_registry_schema():
    # An older checker copy in a team's CI rejects any new field in seams.json. Keeping saved
    # settings in their own file means a save can never turn that CI red or quiet the hooks.
    assert "preset" not in check.SCHEMA["properties"]
    assert "changes" not in check.SCHEMA["properties"]


def test_committed_settings_schema_matches_generated():
    committed = json.loads((ROOT / "schema/seams.settings.schema.json").read_text())
    assert committed == check.SETTINGS_SCHEMA, "run: seams schema --settings --write schema/seams.settings.schema.json"


def test_schema_command_prints_the_settings_schema(capsys):
    assert cli.main(["schema", "--settings"]) == 0
    assert json.loads(capsys.readouterr().out) == check.SETTINGS_SCHEMA


def test_copied_checker_validates_settings_alone(tmp_path):
    # The copy in a team's repo runs with no package around it.
    script = tmp_path / "seams_check.py"
    script.write_text((ROOT / "src/seams/check.py").read_text())
    (tmp_path / "r").mkdir()
    repo = _repo(tmp_path / "r")
    (repo / "seams.settings.json").write_text(json.dumps({"schema_version": 1, "preset": "nope"}))
    out = subprocess.run([sys.executable, str(script), "--root", str(repo)], capture_output=True, text=True)
    assert out.returncode == 1
    assert "seams.settings.json.preset" in out.stdout
