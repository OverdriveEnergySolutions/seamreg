"""The convention lead: a pattern most members of a family follow, and the members that break it."""
from __future__ import annotations

from seams.scan import conventions
from seams.scan.inventory import Inventory


def write(root, files):
    for path, text in files.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def leads(root):
    return conventions.find(Inventory(root))


def index(name, fields):
    body = "".join(f"        ('{f}', 100),\n" for f in fields)
    return f"class {name}Index(SearchIndex):\n    model = {name}\n    fields = (\n{body}    )\n\n\n"


def test_a_class_that_breaks_its_familys_field_list(tmp_path):
    # Seven indexes list 'comments'; DeviceRole's does not (netbox's real drift, shrunk).
    names = ["Site", "Rack", "Device", "Tenant", "Region", "Cable", "Platform", "DeviceRole"]
    text = "".join(index(n, ["name", "description"] + ([] if n == "DeviceRole" else ["comments"])) for n in names)
    write(tmp_path, {"app/search.py": text})
    found = [l for l in leads(tmp_path) if l.extra["family"] == "SearchIndex"]
    assert len(found) == 1
    assert found[0].extra["breakers"] == ["DeviceRoleIndex"]
    assert found[0].extra["pattern"][0]["has"] == "'comments'"
    assert found[0].locs[0] == ("app/search.py", text.split("\n").index("class DeviceRoleIndex(SearchIndex):") + 1, None)
    assert "7 of 8" in found[0].detail


def query(name, join=True):
    return (f"export async function {name}(websiteId, filters) {{\n"
            f"  const {{ filterQuery, {'joinSessionQuery, ' if join else ''}queryParams }} = parseFilters(filters);\n"
            f"  return rawQuery(`select 1 from website_event {'${joinSessionQuery} ' if join else ''}${{filterQuery}}`, queryParams);\n"
            "}\n")


def test_a_file_that_breaks_a_conditional_pattern(tmp_path):
    # Every query file that splices filterQuery also splices joinSessionQuery, except one.
    files = {f"src/queries/sql/q{i}.ts": query(f"getQ{i}") for i in range(7)}
    files["src/queries/sql/replays.ts"] = query("getReplays", join=False)
    files["src/queries/sql/index.ts"] = "export * from './q0';\n"  # gathers the others: not a member
    for i in range(3):  # files that never filter: outside the condition
        files[f"src/queries/sql/save{i}.ts"] = f"export async function saveThing{i}(data) {{ return runQuery(data); }}\n"
    write(tmp_path, files)
    found = [l for l in leads(tmp_path) if "src/queries/sql/replays.ts" in l.extra["breakers"]]
    assert found
    assert any(p["has"] == "joinSessionQuery" for p in found[0].extra["pattern"])
    assert all("index.ts" not in b for l in leads(tmp_path) for b in l.extra["breakers"])


def test_a_family_that_agrees_gives_no_lead(tmp_path):
    names = ["Site", "Rack", "Device", "Tenant", "Region", "Cable", "Platform"]
    write(tmp_path, {"app/search.py": "".join(index(n, ["name", "comments"]) for n in names)})
    assert not leads(tmp_path)


def test_a_name_every_kind_of_file_uses_is_not_a_files_pattern(tmp_path):
    # useState is in most of these components, and in as many files elsewhere: not this folder's own rule.
    files = {}
    for i in range(8):
        hook = "useState" if i < 7 else "useReducer"
        files[f"web/a/C{i}.tsx"] = f"export function C{i}() {{ const [x, setX] = {hook}(0); return x; }}\n"
        files[f"app/b/D{i}.tsx"] = f"export function D{i}() {{ const [y, setY] = useState(1); return y; }}\n"
    write(tmp_path, files)
    assert not [l for l in leads(tmp_path) if "web/a/C7.tsx" in l.extra["breakers"]
                and any(p["has"] == "useState" for p in l.extra["pattern"])]


def test_imports_and_css_classes_are_not_patterns(tmp_path):
    files = {}
    for i in range(8):
        imp = "import axios from 'axios';\n" if i < 7 else ""
        files[f"web/n/N{i}.vue"] = (f"<template><div class=\"{'form-label' if i < 7 else 'x'}\"></div></template>\n"
                                    f"<script>\n{imp}export default {{ name: 'N{i}' }}\n</script>\n")
    write(tmp_path, files)
    assert not leads(tmp_path)
