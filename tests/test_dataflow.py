"""Flow and access leads."""
from __future__ import annotations

from seams.scan import dataflow
from seams.scan.inventory import Inventory


def write(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


FILLER = {f"lib/mod{i}/f.py": f"value_number_{i} = {i}\n" for i in range(10)}


def test_a_key_written_in_one_folder_and_read_in_another_makes_a_flow_lead(tmp_path):
    write(tmp_path, {"app/enrich/sub.php": "$row['pay_dates'] = $dates;\n$row['paid_dates'] = $p;\n",
                     "app/http/index.php": "echo $bill['pay_dates'];\nfoo($bill['paid_dates']);\n", **FILLER})
    leads = [l for l in dataflow.find(Inventory(tmp_path)) if l.kind == "flow"]
    assert [sorted(p for p, _, _ in l.locs) for l in leads] == [["app/enrich/sub.php", "app/http/index.php"]]
    assert "pay_dates" in leads[0].detail


def test_two_files_deciding_access_with_the_same_rare_names_make_an_access_lead(tmp_path):
    rule = "if (!user.isAdmin && !project.owner_override_flag) { forbidden(); }\nauthorize(project.owner_override_flag)\n"
    write(tmp_path, {"web/projects/edit.ts": rule, "api/projects/update.ts": rule, **FILLER})
    leads = [l for l in dataflow.find(Inventory(tmp_path)) if l.kind == "access"]
    assert any(sorted(p for p, _, _ in l.locs) == ["api/projects/update.ts", "web/projects/edit.ts"] for l in leads)
