"""Miss reports: drift no seam listed, recorded so seamreg can learn the shape."""
from __future__ import annotations

import json

from seams import cli, misses

SEAM = {"id": "s", "title": "S", "kind": "vocabulary", "must_agree": "Same.", "risk": "low", "consequence": "c",
        "copies": [{"path": "api/a.py"}, {"path": "web/b.ts"}]}


def repo(tmp_path, seams=()):
    for f in ("api/a.py", "web/b.ts", "web/c.ts", "docs/d.md"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n")
    if seams is not None:
        (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": list(seams)}))
    return tmp_path


def test_registry_state():
    data = {"seams": [SEAM, dict(SEAM, id="g", copies=[{"path": "api/a.py"}, {"path": "web/*.ts"}])]}
    assert misses.registry_state(None, ["api/a.py"], ["web/b.ts"]) == "no-registry"
    assert misses.registry_state(data, ["api/a.py"], ["web/b.ts"]) == "recorded-rule-missing"
    assert misses.registry_state(data, ["api/a.py"], ["web/c.ts"]) == "glob-only"
    assert misses.registry_state(data, ["docs/d.md"], ["web/b.ts"]) == "none"


def test_a_private_report_shares_only_the_shape(tmp_path, capsys):
    root = repo(tmp_path)
    assert cli.main(["report-miss", "--root", str(root), "--changed", "api/a.py", "--missed", "docs/d.md",
                     "--rule", "The doc lists every status the API has.", "--shape", "doc-claims",
                     "--summary", "A doc lists the values an API accepts.",
                     "--cause", "abc1234", "--fix", "def5678", "--repo", "https://example.invalid/r"]) == 0
    out = capsys.readouterr().out
    shared = out.split("Saved the full report")[0]
    assert "api/a.py" not in shared and "docs/d.md" not in shared and "abc1234" not in shared
    assert "example.invalid" not in shared and "changed .py file" in shared and "missed .md file" in shared
    [saved] = (root / ".seams-scan/misses").glob("*.json")
    full = json.loads(saved.read_text())
    assert full["copies"][0]["path"] == "api/a.py"           # the local copy keeps the paths
    assert full["commits"] is None and full["repo"] is None  # but never the repo or commits when not public
    assert full["registry"] == "none" and not misses.errors(full)


def test_a_private_report_never_shares_the_rule_notes_or_file_names(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "secret-billing-cfg").write_text("x\n")
    assert cli.main(["report-miss", "--root", str(root), "--changed", "api/a.py", "--missed", "secret-billing-cfg",
                     "--rule", "api/a.py STATUSES must match secret-billing-cfg in AcmeCorp's billing service",
                     "--summary", "A config file repeats a list the code defines.", "--notes", "AcmeCorp ticket 42"]) == 0
    shared = capsys.readouterr().out.split("Saved the full report")[0]
    for secret in ("api/a.py", "secret-billing-cfg", "AcmeCorp", "STATUSES", "ticket 42"):
        assert secret not in shared, secret
    assert "no-extension" in shared and "kept private" in shared


def test_a_private_report_needs_a_summary(tmp_path, capsys):
    root = repo(tmp_path)
    assert cli.main(["report-miss", "--root", str(root), "--changed", "api/a.py", "--missed", "web/b.ts",
                     "--rule", "api/a.py and web/b.ts agree"]) == 2
    assert "needs --summary" in capsys.readouterr().err
    assert not (root / ".seams-scan/misses").exists()


def test_a_generic_file_name_is_its_type():
    assert misses.file_type("deploy/Dockerfile") == "Dockerfile" and misses.file_type("a/b.py") == ".py"
    assert misses.file_type("ops/acme-secrets") == "no-extension"
    assert misses.file_type("ops/invoice.acme-billing") == "other"  # a suffix can carry a name


def test_an_odd_suffix_never_reaches_the_shared_text_or_languages(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "invoice.acme-billing").write_text("x\n")
    r = misses.make_report(root, ["api/a.py"], ["invoice.acme-billing"], "rule", "A data file repeats a list.")
    shared = misses.shareable(r)
    assert "acme" not in json.dumps(shared) and shared["languages"] == ["py"]
    assert "acme" not in misses.render_md(r)


def test_a_public_report_keeps_what_a_replay_needs(tmp_path, capsys):
    root = repo(tmp_path, [SEAM])
    cli.main(["report-miss", "--root", str(root), "--changed", "api/a.py", "--missed", "web/b.ts", "--rule", "Same list.",
              "--cause", "abc1234", "--fix", "def5678", "--repo", "https://example.invalid/r", "--public"])
    out = capsys.readouterr().out
    assert "abc1234" in out and "`web/b.ts`" in out and "example.invalid" in out
    assert "already lists both copies" in out  # SEAM names both: its rule needs sharpening, not a new seam


def test_catalog_ranks_unhandled_shapes_first(tmp_path):
    def rep(i, shape, handled):
        r = misses.make_report(tmp_path, ["a.py"], ["b.ts"], "rule", f"summary {i}", shape, today="2026-01-01")
        r["id"], r["handled_by"] = f"r{i}", handled
        (tmp_path / f"r{i}.json").write_text(json.dumps(r))
    rep(1, "twins", None); rep(2, "twins", None); rep(3, "siblings", "focus:siblings"); rep(4, "writers", None)
    (tmp_path / "bad.json").write_text('{"id": "x"}')  # an invalid report is left out
    text = misses.catalog_text(misses.load_library([tmp_path]))
    assert text.startswith("# Miss library: 4 reports")
    assert text.index("| twins | 2 | 2") < text.index("| writers | 1 | 1") < text.index("| siblings | 1 | 0")


def test_the_shipped_library_is_valid_and_public():
    reports = misses.load_library()
    assert len(reports) >= 13
    for path, r in reports:
        assert not misses.errors(r) and r["public"] and r["commits"] and r["repo"].startswith("https://github.com/")


def test_benchmark_runs_cannot_be_handed_the_library():
    # Reviewer-visible text must not point at the library: it holds benchmark answers.
    from pathlib import Path
    root = Path(misses.__file__).parents[2]
    for f in list((root / "skills").rglob("*.md")) + list((root / "agents").glob("*.md")) + [
            root / "src/seams/brief.md", root / "src/seams/verify-brief.md", root / "src/seams/tie-brief.md"]:
        assert "catalog/" not in f.read_text(), f
