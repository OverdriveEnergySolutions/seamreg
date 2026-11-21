"""Presets: what each one runs, how a team's changes layer on top, and what a run will cost."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from seams import check, cli, presets, spend

ROOT = Path(__file__).resolve().parents[1]


def test_each_preset_names_a_model_and_effort_for_every_step():
    for name, steps in presets.DEFINITIONS.items():
        assert set(steps) == set(check.STEPS), name
        for step, fields in steps.items():
            assert fields["model"] in check.MODELS and fields["effort"] in check.EFFORTS, (name, step)
    assert set(presets.DEFINITIONS) == set(check.PRESETS)


def test_standard_and_all_in_differ_where_the_measurements_say():
    std, top = presets.DEFINITIONS["standard"], presets.DEFINITIONS["all-in"]
    assert std["lead_check"] == {"model": "sonnet", "effort": "high"}
    assert top["lead_check"] == {"model": "sonnet", "effort": "max"}
    assert all(f["effort"] == "max" for f in top.values())
    assert std["review"] == top["review"] == {"model": "sonnet", "effort": "max"}
    assert std["rerate"]["model"] == top["rerate"]["model"] == "opus"


def test_every_measured_rate_uses_allowed_values():
    for step, model, effort in presets.RATES:
        assert step in check.STEPS and model in check.MODELS and effort in check.EFFORTS


def test_tool_text_names_no_benchmark_repo():
    text = (ROOT / "src/seams/presets.py").read_text().lower()
    for name in ("vaultwarden", "dawarich", "firefly", "umami", "memos"):
        assert name not in text


def test_saved_changes_and_this_runs_changes_layer_on_the_preset():
    saved = {"schema_version": 1, "preset": "standard", "changes": {"lead_check": {"effort": "xhigh"}}}
    s = presets.resolve("standard", saved, ["review.model=opus"])
    assert s["steps"]["lead_check"]["effort"] == {"value": "xhigh", "source": "saved"}
    assert s["steps"]["review"]["model"] == {"value": "opus", "source": "this run"}
    assert s["steps"]["drift_check"]["model"]["source"] == "preset"


def test_saved_changes_apply_only_to_the_saved_preset():
    saved = {"schema_version": 1, "preset": "standard", "changes": {"lead_check": {"effort": "xhigh"}}}
    assert presets.resolve("all-in", saved)["steps"]["lead_check"]["effort"]["value"] == "max"


@pytest.mark.parametrize("bad", ["lead_check.effort", "lead_chek.effort=high", "review.colour=red",
                                 "review.effort=extreme"])
def test_a_bad_change_is_refused_with_its_text(bad):
    with pytest.raises(ValueError, match=re.escape(bad)):
        presets.parse_set(bad)


def test_an_effort_above_every_measured_one_errs_high():
    measured, ok = presets.rate("lead_check", "sonnet", "high")
    stretched, ok2 = presets.rate("rerate", "opus", "max")
    assert ok and not ok2
    assert stretched == pytest.approx(presets.RATES[("rerate", "opus", "medium")] * presets.MAX_STRETCH)


def test_an_unmeasured_effort_between_measured_ones_borrows_the_higher():
    r, measured = presets.rate("lead_check", "sonnet", "xhigh")
    assert r == presets.RATES[("lead_check", "sonnet", "max")] and not measured


def test_an_unmeasured_model_has_no_estimate():
    r, _ = presets.rate("lead_check", "haiku", "high")
    assert r is None
    work = {"review": 1000, "lead_check": 10, "drift_check": 1, "rerate": 1,
            "packets": {"review": 1, "lead_check": 1, "drift_check": 1, "rerate": 1}}
    eff = presets.plain(presets.resolve("standard", sets=["lead_check.model=haiku"]))
    assert presets.estimate(eff, work)["agents"] is None


def test_the_estimate_adds_the_steps_and_counts_the_session_separately():
    work = {"review": 100_000, "lead_check": 1000, "drift_check": 10, "rerate": 50,
            "packets": {"review": 2, "lead_check": 40, "drift_check": 10, "rerate": 2}}
    est = presets.estimate(presets.plain(presets.resolve("standard")), work)
    review = 100_000 * presets.RATES[("review", "sonnet", "max")] + 2 * presets.REVIEW_PACKET[("review", "sonnet", "max")]
    want = review + 1000 * 0.00425 + 10 * 1.01 + 50 * 0.0183
    assert est["agents"] == pytest.approx(want, abs=0.02)
    assert est["orchestrator"] == pytest.approx(want * presets.ORCHESTRATOR_SHARE, abs=0.02)
    assert est["steps"]["review"]["per_packet"] == pytest.approx(review / 2, abs=0.01)


def test_a_small_review_packet_still_costs_its_fixed_part():
    # Measured: a 6,406-line packet cost $8.15. A rate per line alone priced it at $1.24.
    work = {"review": 6406, "lead_check": 0, "drift_check": 0, "rerate": 0,
            "packets": {"review": 1, "lead_check": 0, "drift_check": 0, "rerate": 0}}
    est = presets.estimate(presets.plain(presets.resolve("standard")), work)
    assert 0.7 * 8.15 < est["steps"]["review"]["dollars"] < 1.3 * 8.15


# --- the report, on a scanned repo -----------------------------------------------

ONE_SEAM = {"schema_version": 1, "seams": [{
    "id": "money", "title": "Money rounding", "kind": "copied-helper", "must_agree": "Both round money the same way.",
    "copies": [{"path": "api/money.py"}, {"path": "worker/money.py"}],
    "consequence": "Invoices and payouts disagree by a cent.", "risk": "medium"}]}


def scanned(tmp_path, registry=None):
    # The scan tests' toy repo has one planted seam per lead kind, so every step has work.
    import shutil
    tmp_path = tmp_path / "repo"
    shutil.copytree(ROOT / "tests" / "fixtures" / "toy-repo", tmp_path)
    (tmp_path / "seams.json").unlink(missing_ok=True)
    if registry is not None:
        (tmp_path / "seams.json").write_text(json.dumps(registry))
    assert cli.main(["scan", "--root", str(tmp_path)]) == 0
    return tmp_path


def test_with_nothing_saved_both_presets_are_offered_with_a_dollar_estimate(tmp_path, capsys):
    root = scanned(tmp_path)
    capsys.readouterr()
    assert cli.main(["presets", "--root", str(root), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["saved"] is None and set(rep["presets"]) == {"standard", "all-in"}
    for row in rep["presets"].values():
        assert isinstance(row["full"]["agents"], float)
    assert rep["presets"]["all-in"]["full"]["agents"] > rep["presets"]["standard"]["full"]["agents"]


def test_the_text_report_links_the_explanation(tmp_path, capsys):
    root = scanned(tmp_path)
    capsys.readouterr()
    assert cli.main(["presets", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "docs/presets.md" in out and "standard" in out and "all-in" in out


def test_a_repo_with_a_registry_also_gets_a_diff_estimate(tmp_path, capsys):
    root = scanned(tmp_path, ONE_SEAM)
    capsys.readouterr()
    assert cli.main(["presets", "--root", str(root), "--json", "--preset", "standard"]) == 0
    row = json.loads(capsys.readouterr().out)["presets"]["standard"]
    assert "diff" in row and row["diff_percent"] is not None


def _ratio_report(monkeypatch, tmp_path, diff_share, saved="standard"):
    root = scanned(tmp_path, ONE_SEAM)
    (root / "seams.settings.json").write_text(json.dumps({"schema_version": 1, "preset": saved}))
    full = {"review": 100_000, "lead_check": 1000, "drift_check": 10, "rerate": 50,
            "packets": {"review": 10, "lead_check": 40, "drift_check": 10, "rerate": 10}}
    diff = {k: round(v * diff_share) for k, v in full.items() if k != "packets"}
    diff["packets"] = {k: round(v * diff_share) for k, v in full["packets"].items()}
    monkeypatch.setattr(presets, "counts", lambda doc, known, new_only=False: diff if new_only else full)
    return presets.report(root, root / ".seams-scan", saved)["presets"][saved]


def test_a_small_diff_runs_on_the_saved_preset(monkeypatch, tmp_path):
    row = _ratio_report(monkeypatch, tmp_path, 0.10)
    assert row["diff_percent"] == 10 and row["diff_over_limit"] is False


def test_a_large_diff_is_over_the_limit(monkeypatch, tmp_path):
    row = _ratio_report(monkeypatch, tmp_path, 0.40, saved="all-in")
    assert row["diff_percent"] == 40 and row["diff_over_limit"] is True


def test_a_changed_definition_is_reported_once_and_keeps_the_teams_change(monkeypatch, tmp_path):
    root = scanned(tmp_path)
    (root / "seams.settings.json").write_text(json.dumps(
        {"schema_version": 1, "preset": "standard", "changes": {"lead_check": {"effort": "xhigh"}}}))
    out = root / ".seams-scan"
    s = presets.resolve("standard")
    spend.start(out, s, estimate=1.0, per_packet={k: 0.1 for k in presets.STEPS})
    spend.finish(out)
    last = spend.last_finished(out)
    assert presets.report(root, out, "standard", last=last)["presets"]["standard"]["definition_changed"] is False
    changed = {**presets.DEFINITIONS, "standard": {**presets.DEFINITIONS["standard"],
                                                   "drift_check": {"model": "sonnet", "effort": "high"}}}
    monkeypatch.setattr(presets, "DEFINITIONS", changed)
    row = presets.report(root, out, "standard", last=last)["presets"]["standard"]
    assert row["definition_changed"] is True
    assert row["settings"]["steps"]["lead_check"]["effort"] == {"value": "xhigh", "source": "saved"}


def test_no_scan_yet_says_to_scan(tmp_path, capsys):
    assert cli.main(["presets", "--root", str(tmp_path)]) == 2
    assert "seams scan" in capsys.readouterr().err


def test_run_start_records_the_estimate_as_its_ceiling(tmp_path, capsys):
    root = scanned(tmp_path)
    capsys.readouterr()
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard", "--json"]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["ceiling"] == run["estimate"] > 0 and run["preset"] == "standard"
    assert set(run["per_packet"]) == set(check.STEPS)


def test_a_step_estimated_at_no_packets_still_reserves_one_packet():
    # A small repo estimates no drift check, but the reviewers may still record seams that need one.
    work = {"review": 4000, "lead_check": 10, "drift_check": 0, "rerate": 2,
            "packets": {"review": 1, "lead_check": 1, "drift_check": 0, "rerate": 1}}
    st = presets.estimate(presets.plain(presets.resolve("standard")), work)["steps"]["drift_check"]
    assert st["dollars"] == 0 and st["per_packet"] == pytest.approx(presets.RATES[("drift_check", "sonnet", "max")])


def test_presets_does_not_import_the_spend_hooks():
    # The hooks import presets. A cycle back would break every hook the day an import moves.
    text = (ROOT / "src/seams/presets.py").read_text()
    assert "import spend" not in text and "spend," not in text


def test_run_start_refuses_a_diff_scan_with_no_registry(tmp_path, capsys):
    root = scanned(tmp_path)
    capsys.readouterr()
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard", "--diff"]) == 2
    assert "--diff" in capsys.readouterr().err and spend.open_run(root / ".seams-scan") is None


def test_run_start_records_a_diff_scans_own_estimate(tmp_path, capsys):
    root = scanned(tmp_path, ONE_SEAM)
    capsys.readouterr()
    assert cli.main(["presets", "--root", str(root), "--json", "--preset", "standard"]) == 0
    want = json.loads(capsys.readouterr().out)["presets"]["standard"]["diff"]["agents"]
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard", "--diff", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["estimate"] == want


def test_run_start_needs_a_preset_and_refuses_a_second_open_run(tmp_path, capsys):
    root = scanned(tmp_path)
    assert cli.main(["run", "start", "--root", str(root)]) == 2
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard"]) == 0
    assert cli.main(["run", "start", "--root", str(root), "--preset", "all-in"]) == 2
    assert "still open" in capsys.readouterr().err


def test_an_unmeasured_run_without_a_ceiling_does_not_start(tmp_path, capsys):
    root = scanned(tmp_path)
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard",
                     "--set", "lead_check.model=haiku"]) == 2
    assert "--ceiling" in capsys.readouterr().err and spend.open_run(root / ".seams-scan") is None


def test_an_empty_registry_from_init_is_a_first_review(tmp_path, capsys):
    root = scanned(tmp_path, {"schema_version": 1, "seams": []})
    capsys.readouterr()
    assert cli.main(["presets", "--root", str(root), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["has_registry"] is False and "diff" not in rep["presets"]["standard"]


def test_a_diff_scans_lead_check_takes_only_the_new_leads(tmp_path, capsys):
    # With every lead in the baseline there is nothing new, so the diff's lead check has nothing to do.
    root = scanned(tmp_path, ONE_SEAM)
    assert cli.main(["baseline", "--root", str(root)]) == 0
    assert cli.main(["scan", "--new", "--root", str(root)]) == 0
    capsys.readouterr()
    assert cli.main(["split", "--lead-check", "--root", str(root)]) == 0
    assert "lead check packets" in capsys.readouterr().out
    assert cli.main(["split", "--lead-check", "--new-only", "--root", str(root)]) == 0
    assert "Nothing to check" in capsys.readouterr().out
