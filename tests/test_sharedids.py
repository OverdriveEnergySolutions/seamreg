"""Shared-identifier leads: two files in different folders that use the same rare names."""
from __future__ import annotations

from seams.scan import sharedids
from seams.scan.inventory import Inventory


def write(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


def test_two_handlers_that_check_the_same_rare_fields_make_a_lead(tmp_path):
    rule = "if account.site_limit_override and account.grandfathered_plan and usage.monthly_pageview_cap:\n"
    write(tmp_path, {"web/billing/limits.py": rule, "api/sites/create_site.py": rule,
                     # filler files so the names are rare among many
                     **{f"lib/mod{i}/f.py": f"value_number_{i} = {i}\n" for i in range(12)}})
    found = sharedids.find(Inventory(tmp_path))
    pairs = [sorted(p for p, _, _ in l.locs) for l in found]
    assert ["api/sites/create_site.py", "web/billing/limits.py"] in pairs
    lead = found[pairs.index(["api/sites/create_site.py", "web/billing/limits.py"])]
    assert lead.kind == "shared-ids" and "site_limit_override" in lead.detail


def test_names_in_many_files_or_in_one_folder_make_no_lead(tmp_path):
    common = "shared_helper_name another_helper_name third_helper_name\n"
    write(tmp_path, {**{f"pkg{i}/a.py": common for i in range(6)},       # in 6 files: too common
                     "same/one.py": "rare_alpha_name rare_beta_name rare_gamma_name\n",
                     "same/two.py": "rare_alpha_name rare_beta_name rare_gamma_name\n",  # one folder: skipped
                     **{f"lib/mod{i}/f.py": f"value_number_{i} = {i}\n" for i in range(12)}})
    assert sharedids.find(Inventory(tmp_path)) == []


def test_tests_and_docs_are_left_out(tmp_path):
    names = "invoice_due_offset payment_grace_days reminder_cadence_days\n"
    write(tmp_path, {"app/billing.py": names, "tests/test_billing.py": names, "docs/billing.md": names,
                     **{f"lib/mod{i}/f.py": f"value_number_{i} = {i}\n" for i in range(12)}})
    assert sharedids.find(Inventory(tmp_path)) == []
