"""Key-writer leads: every file that writes the same key."""
from __future__ import annotations

from seams.scan import keywriters
from seams.scan.inventory import Inventory


def write(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


def test_three_writers_of_one_key_in_two_folders_make_one_lead(tmp_path):
    write(tmp_path, {"app/enrich/sub.php": "$row['pay_dates'] = $dates;\n",
                     "app/transform/bill.php": "return ['pay_dates' => $this->dates()];\n",
                     "app/jobs/warn.php": "$data['pay_dates'] = [];\n",
                     "app/http/index.php": "echo $bill['pay_dates'];\n"})  # a reader, not a writer
    leads = [l for l in keywriters.find(Inventory(tmp_path)) if l.extra["key"] == "pay_dates"]
    assert len(leads) == 1 and leads[0].kind == "key-writers"
    assert sorted(p for p, _, _ in leads[0].locs) == ["app/enrich/sub.php", "app/jobs/warn.php", "app/transform/bill.php"]


def test_common_keys_one_folder_and_too_few_writers_make_no_lead(tmp_path):
    write(tmp_path, {**{f"m{i}/a.py": "x = {'name': 1, 'two_writers_only': 2}\n" for i in range(2)},
                     **{f"same/f{i}.py": "x = {'one_folder_key': 1}\n" for i in range(4)},
                     **{f"t{i}/test_a.py": "x = {'only_in_tests': 1}\n" for i in range(4)}})
    keys = {l.extra["key"] for l in keywriters.find(Inventory(tmp_path))}
    assert not keys & {"name", "two_writers_only", "one_folder_key", "only_in_tests"}
