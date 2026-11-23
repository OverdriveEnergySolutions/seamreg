"""The scan against tests/fixtures/toy-repo, which has one planted seam per lead kind."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from seams import cli, scan
from seams.scan.inventory import Inventory, is_test

TOY = Path(__file__).parent / "fixtures" / "toy-repo"


@pytest.fixture(scope="module")
def doc():
    return scan.scan(TOY)


def leads(doc, kind):
    return [[(f["path"], f.get("line")) for f in l["files"]] for l in doc["leads"] if l["kind"] == kind]


def test_areas_come_from_manifests_and_top_folders(doc):
    # web/admin has its own package.json, so it is an area apart from web.
    assert {a["area"] for a in doc["areas"]} == {"api", "web", "web/admin", "worker", "deploy"}


def test_env_name_only_in_config_is_not_a_lead(doc):
    # LOG_LEVEL is in compose and an env file, but no code reads it.
    assert not any("LOG_LEVEL" in l["detail"] for l in doc["leads"])


def test_minified_file_without_min_in_its_name_stays_out(doc):
    every = {f["path"] for l in doc["leads"] for f in l["files"]}
    assert "web/src/bundle.js" not in every


def test_marker_links_the_file_it_names(doc):
    assert [("api/orders/status.py", 1), ("web/src/status.ts", None)] in leads(doc, "marker")


def test_literal_set_reports_the_drifted_item(doc):
    found = [l for l in doc["leads"] if l["kind"] == "literal-set"
             and not any(f["path"].endswith(".md") for f in l["files"])]
    assert len(found) == 1
    assert [(f["path"], f["line"]) for f in found[0]["files"]] == [
        ("api/orders/status.py", 2), ("web/src/status.ts", 1)]
    assert found[0]["extra"]["only_first"] == ["returned"]


def test_copied_block_across_areas(doc):
    assert [("api/orders/billing.py", 1), ("worker/billing_copy.py", 1)] in leads(doc, "dupblock")


def test_same_name_across_languages(doc):
    assert [("api/orders/status.py", 5), ("web/src/status.ts", 3)] in leads(doc, "same-name")


def test_same_constant(doc):
    assert [("api/orders/status.py", 2), ("web/src/status.ts", 1)] in leads(doc, "same-constant")


def test_line_numbers_point_at_the_name_not_a_blank_line_above(doc):
    # A ^\s* pattern can start matching on an earlier blank line.
    assert [("api/settings.py", 3), ("worker/config.py", 3)] in leads(doc, "same-constant")


def test_env_name_in_code_and_config(doc):
    assert [("api/settings.py", 3), ("deploy/compose.yml", 4), ("worker/config.py", 3)] in leads(doc, "env-name")


def test_same_file_name(doc):
    assert [("api/money.py", None), ("worker/money.py", None)] in leads(doc, "same-file")


def test_tie_candidates(doc):
    found = leads(doc, "tie-candidate")
    assert [("api/tests/test_status.py", 4)] in found
    assert [("api/tests/test_status.py", 5), ("web/src/status.ts", None)] in found


def test_dependency_minified_and_generated_files_stay_out(doc):
    every = {f["path"] for l in doc["leads"] for f in l["files"]}
    assert not any(p.startswith("web/node_modules/") for p in every)
    assert "web/src/app.min.js" not in every
    assert "api/orders/generated_client.py" not in every
    assert doc["generated_files"] == ["api/orders/generated_client.py"]


def test_cross_area_leads_sort_first_within_a_kind(doc):
    ties = [l for l in doc["leads"] if l["kind"] == "tie-candidate"]
    assert ties[0]["cross_area"] and not ties[-1]["cross_area"]


def test_counts_match_the_leads(doc):
    for kind, c in doc["counts"].items():
        rows = [l for l in doc["leads"] if l["kind"] == kind]
        assert c["all"] == len(rows)
        assert c["cross_area"] == sum(l["cross_area"] for l in rows)


@pytest.mark.parametrize("path, expected", [
    ("api/tests/x.py", True), ("api/test_x.py", True), ("pkg/x_test.go", True),
    ("web/src/a.test.ts", True), ("web/src/a.spec.tsx", True), ("api/conftest.py", True),
    ("api/latest.py", False), ("api/contest/x.py", False), ("web/src/testing.ts", False),
])
def test_is_test(path, expected):
    assert is_test(path) is expected


def test_git_mode_reads_tracked_and_unignored_files_only(tmp_path):
    if not shutil.which("git"):
        pytest.skip("needs git")
    repo = tmp_path / "toy"
    shutil.copytree(TOY, repo)
    (repo / ".gitignore").write_text("worker/\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    inv = Inventory(repo)
    assert inv.source == "git"
    assert not any(p.startswith("worker/") for p in inv.read)
    assert "api/orders/status.py" in inv.read  # untracked but not ignored: still read
    # git lists node_modules here (nothing ignores it), so the scan must skip it itself
    assert not any(p.startswith("web/node_modules/") for p in inv.read)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_walk_mode_does_not_follow_a_symlink_loop(tmp_path):
    repo = tmp_path / "toy"
    shutil.copytree(TOY, repo)
    os.symlink(repo, repo / "api" / "loop")
    inv = Inventory(repo)
    assert not any("/loop/" in p for p in inv.read)


def test_cli_writes_both_files_and_ignores_its_own_folder(tmp_path, capsys):
    out = tmp_path / "out"
    assert cli.main(["scan", "--root", str(TOY), "--out", str(out)]) == 0
    data = json.loads((out / "leads.json").read_text())
    assert data["leads_version"] == scan.LEADS_VERSION
    assert (out / "leads.md").read_text().startswith("# Seam scan leads")
    assert (out / ".gitignore").read_text() == "*\n"
    assert "Leads are hints, not seams." in capsys.readouterr().out


def test_cli_scan_on_a_missing_root_exits_2(tmp_path):
    assert cli.main(["scan", "--root", str(tmp_path / "nope")]) == 2


# --- docs that state code facts --------------------------------------------------------

def test_a_doc_table_of_names_is_matched_against_the_code_list(doc):
    pairs = leads(doc, "literal-set")
    assert any(("api/orders/statuses.md", 5) in p and ("api/orders/status.py", 2) in p for p in pairs), pairs


def test_a_doc_line_that_names_the_file_it_must_match_is_a_marker(doc):
    assert [("api/orders/statuses.md", 3), ("api/orders/status.py", None)] in leads(doc, "marker")


def test_a_doc_line_that_names_no_file_is_not_a_marker(doc):
    assert not any(("api/orders/statuses.md", 12) in p for p in leads(doc, "marker"))


def test_docs_do_not_count_toward_packet_size(doc):
    from seams import split
    units, _ = split._units(doc, split.DEFAULT_MAX_LINES)
    api_code = sum(f["lines"] for f in doc["files"] if f["area"] == "api" and not f["test"] and not f["doc"])
    assert units["api"] == api_code


def test_docs_never_join_the_name_detectors(doc):
    every = {f["path"] for l in doc["leads"] if l["kind"] in ("same-file", "env-name", "same-name", "same-constant")
             for f in l["files"]}
    assert not any(p.endswith(".md") for p in every)


# --- lists in JSON and between docs ---------------------------------------------------------

def _scan_files(tmp_path, files):
    for p, text in files.items():
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text(text)
    return scan.scan(tmp_path)


def _lit_pairs(doc):
    return [sorted(f["path"] for f in l["files"]) for l in doc["leads"] if l["kind"] == "literal-set"]


SKILLS = ["ask", "tdd", "triage", "wayfinder", "prototype"]


def test_a_json_list_of_paths_matches_a_doc_list_of_links(tmp_path):
    manifest = '{"skills": [' + ", ".join(f'"./skills/{s}"' for s in SKILLS) + "]}\n"
    readme = "# Skills\n\n" + "".join(f"- **[{s}](./skills/{s}/SKILL.md)**: does a thing.\n" for s in SKILLS)
    doc = _scan_files(tmp_path, {"plugin.json": manifest, "README.md": readme})
    assert ["README.md", "plugin.json"] in _lit_pairs(doc)


def test_two_docs_that_list_the_same_names_are_a_lead(tmp_path):
    a = "Roles: " + ", ".join(f"`{s}`" for s in SKILLS) + ".\n"
    doc = _scan_files(tmp_path, {"docs/a.md": a, "docs/b.md": "The roles:\n\n" + a})
    assert ["docs/a.md", "docs/b.md"] in _lit_pairs(doc)


def test_a_list_split_under_headings_matches_through_the_whole_doc(tmp_path):
    # Neither half alone shares enough with the full list; the doc as a whole does.
    split_doc = ("## User-invoked\n\n" + "".join(f"- [{s}](./{s}/SKILL.md)\n" for s in SKILLS[:3])
                 + "\n## Model-invoked\n\n" + "".join(f"- [{s}](./{s}/SKILL.md)\n" for s in SKILLS[3:]))
    full = "All: " + ", ".join(f"`{s}`" for s in SKILLS) + "\n"
    doc = _scan_files(tmp_path, {"README.md": split_doc, "docs/index.md": full})
    lead = next(l for l in doc["leads"] if l["kind"] == "literal-set")
    assert {f["path"]: f["line"] for f in lead["files"]}["README.md"] == 1


def test_the_tools_own_files_are_not_scanned(tmp_path):
    from seams import cli
    cli.main(["init", "--root", str(tmp_path), "--checker", "tools/check_seams.py"])
    (tmp_path / ".claude/rules/seams").mkdir(parents=True)
    (tmp_path / ".claude/rules/seams/x.md").write_text("`a` `b` `c` `d`\n")
    doc = scan.scan(tmp_path)
    paths = {f["path"] for f in doc["files"]}
    assert not paths & {"tools/check_seams.py", "seams.json", ".claude/rules/seams/x.md"}
    assert doc["leads"] == []


def test_a_doc_names_commands_and_folders_in_backticks(tmp_path):
    # A router lists skills as `/tdd`; a guide lists folders as `engineering/`.
    router = "Use " + ", ".join(f"`/{s}`" for s in SKILLS) + ".\n"
    guide = "Skills: " + ", ".join(f"`{s}/`" for s in SKILLS) + ".\n"
    doc = _scan_files(tmp_path, {"router.md": router, "guide.md": guide})
    assert ["guide.md", "router.md"] in _lit_pairs(doc)


# --- what the scan skips, and says it skipped ----------------------------------------------

def test_one_long_line_is_not_minified():
    # tsc writes `exports.a = exports.b = ... = void 0;` near the top of a readable file.
    from seams.scan.inventory import is_minified
    readable = "\n".join(["// header"] * 5 + ["exports.a = " + "exports.b = " * 120 + "void 0;"] + ["x = 1;"] * 40)
    assert not is_minified(readable)
    assert is_minified("\n".join(["var a=" + "b," * 600] * 3))
    assert is_minified("x" * 5000)


def test_a_compiled_file_is_read_and_a_minified_one_is_reported(tmp_path):
    compiled = "exports.a = " + "exports.b = " * 120 + "void 0;\n" + "function f() {}\n" * 30
    (tmp_path / "util.js").write_text(compiled)
    (tmp_path / "bundle.js").write_text(("var a=" + "b," * 600 + "\n") * 3)
    doc = scan.scan(tmp_path)
    assert "util.js" in {f["path"] for f in doc["files"]}
    assert doc["skipped_files"] == {"bundle.js": "minified"}


def test_the_plan_names_unread_and_generated_files(tmp_path):
    from seams import split
    (tmp_path / "bundle.js").write_text(("var a=" + "b," * 600 + "\n") * 3)
    (tmp_path / "gen.py").write_text("# @generated by protoc\nX = 1\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    doc = scan.scan(tmp_path)
    out = tmp_path / ".seams-scan"
    split.write(doc, tmp_path, out)
    plan = (out / "plan.md").read_text()
    assert "- `bundle.js`: minified" in plan and "- `gen.py`" in plan


def test_the_tools_own_files_are_not_counted_as_not_scanned(tmp_path):
    cli.main(["init", "--root", str(tmp_path)])
    (tmp_path / "a.py").write_text("x = 1\n")
    doc = scan.scan(tmp_path)
    assert "json" not in doc["skipped_types"] and doc["skipped_files"] == {}


def test_a_copied_in_library_is_skipped_and_listed():
    from seams.scan.inventory import vendored
    bootstrap = ("/*!\n  * Bootstrap v5.3.8 (https://getbootstrap.com/)\n  * Copyright 2011-2025 The Bootstrap Authors\n"
                 "  * Licensed under MIT\n  */\n(function (global, factory) {\n")
    tables = ("/*\n * This combined file was created by the DataTables downloader builder\n */\n\n"
              "/*! DataTables 2.3.8\n * © SpryMedia Ltd - datatables.net/license\n */\n\n(function(\n")
    assert vendored("src/static/scripts/bootstrap.bundle.js", bootstrap) == "vendored: Bootstrap v5.3.8"
    assert vendored("src/static/scripts/datatables.js", tables) == "vendored: DataTables 2.3.8"
    assert vendored("src/static/scripts/jdenticon-3.3.0.js", "var x = 1;\n") == "vendored: version in the file name"
    assert vendored("lib/jquery-4.0.0.slim.js", "") == "vendored: version in the file name"


def test_a_projects_own_file_is_not_a_library():
    from seams.scan.inventory import vendored
    own = '"use strict";\n/* eslint-env browser */\n// Uses Bootstrap v5.3.8, Copyright The Bootstrap Authors\n'
    apache = ("// Copyright 2024 Google LLC\n//\n// Licensed under the Apache License, Version 2.0 (the \"License\");\n"
              "\nimport { x } from './y';\n")
    later = "const a = 1;\n/* Bootstrap v5.3.8, Licensed under MIT */\n"
    assert vendored("src/static/scripts/admin.js", own) is None
    assert vendored("web/src/types/proto/http_pb.ts", apache) is None
    assert vendored("web/app.js", later) is None
    assert vendored("migrations/2024-01-01-000000_init.sql", "") is None


def test_the_inventory_skips_a_library_and_says_why(tmp_path):
    from seams.scan.inventory import Inventory
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "jquery-4.0.0.slim.js").write_text("(function(){})();\n")
    (tmp_path / "static" / "app.js").write_text("function go() { return 1; }\n")
    inv = Inventory(tmp_path)
    assert inv.read == ["static/app.js"]
    assert inv.skipped == {"static/jquery-4.0.0.slim.js": "vendored: version in the file name"}


@pytest.mark.parametrize("name", ["Eclipse Public License v2.0", "Mozilla Public License Version 2.0",
                                  "Boost Software License 1.0", "Creative Commons Attribution 4.0"])
def test_a_license_name_with_a_version_is_not_a_library(name):
    from seams.scan.inventory import vendored
    assert vendored("src/Main.java", f"/*\n * This program is made available under the {name}\n * Copyright 2024\n */\n") is None
    assert vendored("src/Main.java", f"// {name}\n// Licensed to the project\n") is None


def test_the_holders_own_product_is_not_a_library():
    from seams.scan.inventory import vendored
    own = "// Copyright (c) 2023 Acme\n// Acme Billing Engine 4.2.1\n"
    assert vendored("src/billing.js", own) is None


def test_real_library_headers_are_still_skipped():
    from seams.scan.inventory import vendored
    jq = "/*!\n * jQuery JavaScript Library v3.7.1\n * Copyright OpenJS Foundation and other contributors\n * Released under the MIT license\n */\n"
    jd = "/**\n * Jdenticon 3.2.0\n * Copyright 2014-2024 Daniel Mester Pirttijarvi\n * Released under the MIT license\n */\n"
    assert vendored("a/jquery.js", jq) == "vendored: JavaScript Library v3.7.1"
    assert vendored("a/jdenticon.js", jd) == "vendored: Jdenticon 3.2.0"
