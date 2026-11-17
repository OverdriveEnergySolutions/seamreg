"""Siblings: classes that share a mixin or base must carry its fields into every layer.

Two models mix in the same base, and each has counterpart classes in other layers named
after it: a form, an import form, a serializer, a filter, a table. The base's fields reach
one model's counterparts and not the other's. No single file shows the gap, and the convention
lead misses it too: the counterparts belong to different families (one import form among
forty), and the mixin's users are too few to make a family.

The signal: for each base that two or more classes use, take the fields it declares. For each
user (a sibling), find its counterparts, classes whose name is the sibling's name plus a layer
word (ExportTemplate + ImportForm). Where one sibling's counterpart in a layer names a field of
the base, and another sibling's counterpart in the same layer does not, that is a lead.
Python classes only, for now.
"""
from __future__ import annotations

import collections
import re

from seams.scan.inventory import Lead, is_test, kind_of

MIN_USERS, MAX_USERS = 2, 40  # siblings a base needs; a base every model uses is a framework class
MAX_FIELDS = 25
PER_BASE = 10
MAX_LEADS = 200
GENERIC = {"object", "Exception", "ABC", "Protocol", "Generic", "TypedDict", "NamedTuple", "Enum", "Model",
           "BaseModel", "TestCase"}
_CLASS = re.compile(r"^([ \t]*)class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.M)
_FIELD = re.compile(r"^(\w+)\s*(?::[^=\n]+)?=|^(\w+)\s*:\s*\w")
_SKIP_FIELDS = {"objects", "Meta", "class", "model", "fields", "exclude", "name", "verbose_name"}


def _classes(text):
    """(line, name, bases, body, indent) for each class, any depth."""
    lines = text.split("\n")
    for m in _CLASS.finditer(text):
        indent = len(m.group(1).expandtabs())
        start = text.count("\n", 0, m.start())
        end = start + 1
        while end < len(lines):
            l = lines[end]
            if l.strip() and len(l) - len(l.lstrip()) <= indent and not l.lstrip().startswith((")", "]", "}")):
                break
            end += 1
        bases = [b.strip().split(".")[-1].split("[")[0] for b in (m.group(3) or "").split(",")
                 if b.strip() and "=" not in b]
        yield start + 1, m.group(2), bases, "\n".join(lines[start + 1:end]), indent


def _own_fields(body):
    """Names a class body declares at its own level: `x = ...` and `x: T`."""
    lines = [l for l in body.split("\n") if l.strip()]
    if not lines:
        return set()
    lead = min(len(l) - len(l.lstrip()) for l in lines)
    out = set()
    for l in lines:
        if len(l) - len(l.lstrip()) != lead:
            continue
        m = _FIELD.match(l.strip())
        name = m and (m.group(1) or m.group(2))
        if name and len(name) >= 3 and not name.startswith("_") and not name.isupper() and name not in _SKIP_FIELDS:
            out.add(name)
    return out


def _mentions(body, field):
    return re.search(rf"(?<![\w]){re.escape(field)}(?![\w])", body) is not None


def find(inv):
    # name -> [(path, line, bases, body)]. One name is often defined once per layer (a model's
    # SyncedDataMixin, a form's, an API's), so every definition is kept and their fields are pooled.
    defs = collections.defaultdict(list)
    for p in inv.read:
        if is_test(p) or kind_of(p) != "code" or not p.endswith(".py") or "/migrations/" in "/" + p:
            continue
        for line, name, bases, body, indent in _classes(inv.text(p)):
            if indent == 0:
                defs[name].append((p, line, bases, body))
    classes = {n: d[0] for n, d in defs.items()}
    users = collections.defaultdict(list)
    for name, ds in defs.items():
        for b in {b for d in ds for b in d[2]}:
            if b not in GENERIC:
                users[b].append(name)

    def has(cls, field, depth=0):
        """The class or one of its bases (in the repo) names the field."""
        if cls not in defs or depth > 3:
            return False
        return any(_mentions(d[3], field) or any(has(b, field, depth + 1) for b in d[2]) for d in defs[cls])

    # Counterparts: Sibling + LayerWord (an upper-case letter follows the sibling's name).
    by_prefix = collections.defaultdict(list)
    names = sorted(classes)
    leads = []
    for base, sibs in sorted(users.items()):
        if base not in classes or not (MIN_USERS <= len(sibs) <= MAX_USERS):
            continue
        fields = sorted(set().union(*(_own_fields(d[3]) for d in defs[base])))[:MAX_FIELDS]
        if not fields:
            continue
        layers = collections.defaultdict(dict)  # layer word -> {sibling: counterpart}
        for s in sibs:
            for n in names:
                if n != s and n.startswith(s) and n[len(s)].isupper() and not n[len(s):].startswith(tuple(sibs)):
                    layers[n[len(s):]][s] = n
        cands = collections.defaultdict(list)  # layer -> leads, strongest first
        for layer, cps in sorted(layers.items()):
            if len(cps) < 2:
                continue
            for f in fields:
                holders = [s for s, c in cps.items() if has(c, f)]
                lacking = [s for s, c in cps.items() if not has(c, f)]
                if not holders or not lacking:
                    continue
                share = len(holders) / len(cps)
                bp, bl = classes[base][:2]
                locs = [classes[cps[s]][:2] + (None,) for s in lacking[:4]]
                locs += [classes[cps[s]][:2] + (None,) for s in holders[:2]] + [(bp, bl, None)]
                detail = (f"{', '.join(sibs[:6])}{' and more' if len(sibs) > 6 else ''} share the base {base}, which "
                          f"declares {f}. In the {layer} layer, {', '.join(cps[s] for s in holders[:3])} name {f}, and "
                          f"{', '.join(cps[s] for s in lacking[:4])} do not. Classes that share a base usually carry its "
                          "fields into every layer the same way. Check whether the ones that lack it have a reason.")
                cands[layer].append(Lead("sibling", locs, detail[:900], score=round(1 + share, 2),
                                         extra={"base": base, "field": f, "layer": layer,
                                                "holders": [cps[s] for s in holders], "lacking": [cps[s] for s in lacking]}))
        # Round-robin over layers, so a cap trims depth, not whole layers (the last layer
        # alphabetically, Serializer, was the one dropped before).
        for layer in cands:
            cands[layer].sort(key=lambda l: -l.score)
        picked, i = [], 0
        while len(picked) < PER_BASE and any(i < len(v) for v in cands.values()):
            picked += [v[i] for v in cands.values() if i < len(v)][:PER_BASE - len(picked)]
            i += 1
        leads += picked
    leads.sort(key=lambda l: -l.score)
    return leads[:MAX_LEADS]
