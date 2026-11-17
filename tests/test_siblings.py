"""Siblings: classes that share a base must carry its fields into every layer."""
from __future__ import annotations

import json

from seams import cli
from seams.scan import inventory, siblings

MODELS = '''
class BillingMixin(models.Model):
    currency = models.CharField(max_length=3)
    due_date = models.DateField(null=True)

    class Meta:
        abstract = True


class Invoice(BillingMixin, PrimaryModel):
    number = models.CharField(max_length=20)


class CreditNote(BillingMixin, PrimaryModel):
    reason = models.TextField()
'''
SERIALIZERS = '''
class InvoiceSerializer(Serializer):
    class Meta:
        model = Invoice
        fields = ("id", "number", "currency", "due_date")


class CreditNoteSerializer(Serializer):
    class Meta:
        model = CreditNote
        fields = ("id", "reason", "currency")
'''
FORMS = '''
class InvoiceForm(ModelForm):
    fields = ("number", "currency", "due_date")


class CreditNoteForm(BillingFormMixin, ModelForm):
    fields = ("reason",)


class BillingFormMixin(Form):
    currency = CharField()
    due_date = DateField()
'''


def repo(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return inventory.Inventory(tmp_path)


def test_a_counterpart_that_lacks_a_field_its_sibling_has(tmp_path):
    leads = siblings.find(repo(tmp_path, {"billing/models.py": MODELS, "billing/api/serializers.py": SERIALIZERS}))
    [lead] = [l for l in leads if l.extra["layer"] == "Serializer"]
    assert lead.extra["field"] == "due_date" and lead.extra["lacking"] == ["CreditNoteSerializer"]
    assert lead.extra["holders"] == ["InvoiceSerializer"] and lead.kind == "sibling"
    assert {p for p, _, _ in lead.locs} == {"billing/api/serializers.py", "billing/models.py"}


def test_a_field_that_arrives_through_the_counterparts_own_base_counts(tmp_path):
    leads = siblings.find(repo(tmp_path, {"billing/models.py": MODELS, "billing/forms.py": FORMS}))
    assert not [l for l in leads if l.extra["layer"] == "Form"]  # CreditNoteForm gets both from BillingFormMixin


def test_fields_pool_across_classes_of_one_name(tmp_path):
    # A model mixin and a form mixin often share one name; the fields of both count.
    split = MODELS.replace("    due_date = models.DateField(null=True)\n", "")
    extra = "class BillingMixin(Form):\n    due_date = DateField()\n"
    leads = siblings.find(repo(tmp_path, {"billing/models.py": split, "billing/mixins.py": extra,
                                           "billing/api/serializers.py": SERIALIZERS}))
    assert any(l.extra["field"] == "due_date" for l in leads)


def test_no_lead_when_every_sibling_agrees_or_there_is_one_user(tmp_path):
    agree = SERIALIZERS.replace('fields = ("id", "reason", "currency")', 'fields = ("id", "reason", "currency", "due_date")')
    assert not siblings.find(repo(tmp_path, {"billing/models.py": MODELS, "billing/api/serializers.py": agree}))
    lone = MODELS.replace("class CreditNote(BillingMixin, PrimaryModel)", "class CreditNote(PrimaryModel)")
    assert not siblings.find(repo(tmp_path, {"billing/models.py": lone, "billing/api/serializers.py": SERIALIZERS}))


def test_tests_and_migrations_are_not_read(tmp_path):
    assert not siblings.find(repo(tmp_path, {"tests/test_models.py": MODELS, "billing/migrations/0001.py": MODELS,
                                             "billing/api/serializers.py": SERIALIZERS}))


def test_split_focus_siblings_makes_one_packet(tmp_path, capsys):
    repo(tmp_path, {"billing/models.py": MODELS, "billing/api/serializers.py": SERIALIZERS})
    seam = {"id": "x", "title": "X", "kind": "vocabulary", "must_agree": "Same.", "risk": "low", "consequence": "c",
            "copies": [{"path": "billing/models.py"}, {"path": "billing/api/serializers.py"}]}
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam]}))
    assert cli.main(["scan", "--root", str(tmp_path)]) == 0
    assert cli.main(["split", "--root", str(tmp_path), "--focus", "siblings"]) == 0
    text = (tmp_path / ".seams-scan/packets/focus-siblings.md").read_text()
    assert "## Focused pass: classes that share a base" in text and "- sibling:" in text
    plan = (tmp_path / ".seams-scan/plan.md").read_text()
    assert "Focused pass (siblings)" in plan and "layer by layer" in plan and "twins" not in plan


def test_the_brief_examples_are_invented():
    from seams import split
    text = split.FOCUS["siblings"]["text"].lower()
    for word in ("netbox", "synceddata", "exporttemplate", "configtemplate", "umami", "frigate", "memos", "kuma"):
        assert word not in text
