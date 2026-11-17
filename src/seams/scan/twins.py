"""Two implementations of one behavior: a parser in Go and its copy in TypeScript, two regexes
for the same line, one query written once per database.

Each twin must give the same answer for the same input, and nothing links them but that
promise. The usual drift is an edge case one side handles and the other does not: a Unicode
character, a length cap, a numbered list item, a NULL. Four signals:

- pattern: two regex literals in different files that are alike but not the same,
- language: files in two languages named for the same thing (tag.go, tag-grammar.ts),
- backend: one file name in sibling folders named for backends (sqlite/, mysql/, postgres/),
- branch: functions in one file whose names differ only by a backend word
  (relationalQuery and clickhouseQuery).
"""
from __future__ import annotations

import collections
import math
import os
import re
from pathlib import PurePosixPath

from seams.scan.inventory import Lead, is_test, kind_of

# --- pattern twins ---------------------------------------------------------------------------
_REGEX = [
    # JS/TS literal after a token that cannot end an expression, so a / is not a division.
    # Not at /* or //: a comment such as /* eslint-disable */ is not a pattern (it was 28 of 31 leads on one repo).
    re.compile(r"(?:[=(,:!&|?{;]|\breturn|^)\s*/(?![*/])((?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\[\n])+)/[dgimsuyv]*", re.M),
    # Exclusive alternatives, one line: `\\.|(?!\1).` let a backslash match both ways and backtrack
    # exponentially on a long unterminated string, and the scan reads untrusted files.
    re.compile(r"\bnew RegExp\(\s*([\"'`])((?:\\.|(?!\1)[^\\\n]){4,})\1"),
    re.compile(r"\bregexp\.(?:Must)?Compile(?:POSIX)?\(\s*(`[^`]{4,}`|\"(?:\\.|[^\"\\]){4,}\")"),  # Go
    re.compile(r"\bre\.(?:compile|match|search|fullmatch|sub|findall|finditer|split)\(\s*r?(\"(?:\\.|[^\"\\]){4,}\"|'(?:\\.|[^'\\]){4,}')"),
    re.compile(r"\bRegex::new\(\s*r?#*\"((?:\\.|[^\"\\]){4,})\""),  # Rust
]
MIN_PATTERN = 10      # characters in a pattern worth comparing
PATTERN_SIM = 0.45    # rarity-weighted share of pieces for two patterns to be twins (0.4 to 0.5 gave the same leads on five repos)
MAX_PATTERNS = 3000
PER_TOKEN = 4         # language-twin pairs kept per shared name token


def _pattern_text(m):
    raw = m.group(m.lastindex)
    if raw[:1] in "`\"'" and raw[-1:] == raw[:1]:
        raw = raw[1:-1]
    return raw


def _grams(s):
    return {s[i:i + 3] for i in range(len(s) - 2)}


# The pieces a regex is built from: escapes, character classes, group openers, anchors, and
# runs of literal text. Two patterns for the same input share their rare pieces ([ xX] for a
# checkbox), while every pattern shares the common ones (^, \s, a group).
_ATOM = re.compile(r"\\.|\[(?:\\.|[^\]\\])*\]|\(\?(?::|<?[=!]|<\w+>)?|[)|^$.]|\{\d+(?:,\d*)?\}|[^\\\[\](){}|^$.*+?]+")


def _atoms(pattern):
    return {m.group(0) for m in _ATOM.finditer(pattern)}


def _weighted(a, b, weight):
    union = a | b
    total = sum(weight(x) for x in union)
    return sum(weight(x) for x in a & b) / total if total else 0.0


def _patterns(inv, code):
    out = []
    for p in code:
        text = inv.text(p)
        for rx in _REGEX:
            for m in rx.finditer(text):
                pat = _pattern_text(m)
                # A pattern is regex-like: it holds a class, a group, an anchor or a quantifier.
                if len(pat) >= MIN_PATTERN and re.search(r"[\[\](){}^$*+?|\\]", pat) and not pat.startswith(("http", "//")):
                    out.append((p, inv.line_at(p, m.start()), pat))
    return out[:MAX_PATTERNS]


def _pattern_twins(inv, code):
    pats = _patterns(inv, code)
    grams = [_atoms(x[2]) for x in pats]
    df = collections.Counter(a for g in grams for a in g)
    weight = lambda a: math.log((1 + len(pats)) / df[a])
    index = collections.defaultdict(list)
    for i, g in enumerate(grams):
        for t in g:
            index[t].append(i)
    shared = collections.Counter()
    for ids in index.values():
        if len(ids) > 60:  # a piece in many patterns ("\s") says little
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                shared[(ids[a], ids[b])] += 1
    leads, seen = [], set()
    for (i, j), n in shared.most_common():
        (pa, la, xa), (pb, lb, xb) = pats[i], pats[j]
        if pa == pb:
            continue
        sim = _weighted(grams[i], grams[j], weight)
        if sim < PATTERN_SIM or (pa, pb) in seen:
            continue
        seen.add((pa, pb))
        same = xa == xb
        detail = (f"Two files hold {'the same' if same else 'a similar'} pattern"
                  f"{'' if same else f' ({round(sim * 100)}% alike)'}: `{xa[:120]}` and `{xb[:120]}`. "
                  "If both match the same input, they must accept and reject the same cases.")
        leads.append(Lead("twin", [(pa, la, None), (pb, lb, None)], detail,
                          score=round(1 + (0 if same else 1) + sim, 2), extra={"signal": "pattern"}))
    return leads


# --- language twins --------------------------------------------------------------------------
LANG = {".go": "Go", ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
        ".jsx": "JavaScript", ".mjs": "JavaScript", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
        ".kt": "Kotlin", ".swift": "Swift", ".dart": "Dart", ".cs": "C#", ".php": "PHP", ".ex": "Elixir"}
GENERIC = set("""
index main util utils helper helpers common types type base core lib api app config constants const
model models service services handler handlers controller controllers router routes route test tests
spec mock mocks store client server web ui view views page pages component components hook hooks
context provider default new old v1 v2 internal pkg cmd src mod init setup error errors log logger
""".split())


def _stem_tokens(path):
    stem = PurePosixPath(path).stem.split(".")[0]
    parts = re.split(r"[-_.]|(?<=[a-z0-9])(?=[A-Z])", stem)
    return {t.lower() for t in parts if len(t) >= 3} - GENERIC


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}|\b\d{2,}\b")


def _vocab(text):
    """Words two implementations of one rule tend to share: names (MaxTagLength and
    MAX_TAG_LENGTH count as one) and numbers of two or more digits."""
    return {w.replace("_", "").lower() for w in _WORD.findall(text)}


def _language_twins(inv, code):
    vocab = {p: _vocab(inv.text(p)) for p in code if LANG.get(os.path.splitext(p)[1])}
    df = collections.Counter(w for v in vocab.values() for w in v)
    rare = max(3, len(vocab) // 50)
    weight = lambda w: math.log((1 + len(vocab)) / df[w]) if df[w] <= rare else 0.0
    by_token = collections.defaultdict(list)
    for p in code:
        lang = LANG.get(os.path.splitext(p)[1])
        if lang:
            for t in _stem_tokens(p):
                by_token[t].append((p, lang))
    leads, seen = [], set()
    for token, files in sorted(by_token.items()):
        langs = {lang for _, lang in files}
        if len(langs) < 2 or len(files) > 30:  # a token in very many files ("memo") names a domain
            continue
        mine = []
        for a in range(len(files)):
            for b in range(a + 1, len(files)):
                (pa, la), (pb, lb) = files[a], files[b]
                if la == lb or {la, lb} == {"TypeScript", "JavaScript"} or (pa, pb) in seen:
                    continue
                ta, tb = _stem_tokens(pa), _stem_tokens(pb)
                jac = len(ta & tb) / len(ta | tb)
                if jac < 0.5:
                    continue
                seen.add((pa, pb))
                detail = (f"A {la} file and a {lb} file are named for the same thing (`{token}`). If both "
                          "parse, validate or format the same input, they are two implementations of one rule.")
                # Two files named alike that share no rare word (a parser and a UI component that
                # shows its result) are one domain, not two implementations.
                shared = _weighted(vocab[pa], vocab[pb], weight)
                if shared == 0:
                    continue
                mine.append(Lead("twin", [(pa, None, None), (pb, None, None)], detail,
                                 score=round(1 + 0.5 * jac + 8 * shared, 2), extra={"signal": "language"}))
        # The closest-named pairs for a token: mention.go and mention-grammar.ts before memo_mention_helpers.go.
        leads += sorted(mine, key=lambda l: -l.score)[:PER_TOKEN]
    return leads


# --- backend twins ---------------------------------------------------------------------------
BACKENDS = set("""
sqlite sqlite3 mysql mariadb postgres postgresql pg pgsql mssql oracle clickhouse ch duckdb mongo mongodb
redis dynamo dynamodb cassandra elastic opensearch prisma relational sql nosql memory inmemory file fs
s3 gcs azure local remote ios android web desktop mobile node browser deno bun linux windows darwin macos
""".split())


def _backend_twins(inv, code):
    groups = collections.defaultdict(list)
    for p in code:
        parts = p.split("/")
        if len(parts) >= 3 and parts[-2].lower() in BACKENDS:
            groups[("/".join(parts[:-2]), parts[-1])].append(p)
    leads = []
    for (parent, name), files in sorted(groups.items()):
        if len(files) < 2:
            continue
        folders = ", ".join(p.split("/")[-2] for p in files)
        detail = (f"`{name}` exists once per backend under `{parent}/` ({folders}). Each copy must give the "
                  "same result for the same request: compare them case by case, NULLs and missing keys too.")
        leads.append(Lead("twin", [(p, None, None) for p in files], detail,
                          score=round(1.5 + 0.2 * len(files), 2), extra={"signal": "backend"}))
    return leads


_FUNC = re.compile(r"(?:\bfunction\s+|\bdef\s+|\bfunc\s+(?:\([^)]*\)\s*)?|\basync\s+function\s+)([A-Za-z_][A-Za-z0-9_]*)"
                   r"|\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\(|function\b|[A-Za-z_]\w*\s*=>)")


def _words(name):
    return [w.lower() for w in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", name) if w]


def _branch_twins(inv, code):
    # One lead per pairing of names: 54 query files that each hold relationalQuery and
    # clickhouseQuery are one family, not 54 leads.
    family = collections.defaultdict(list)
    for p in code:
        funcs = {}
        for m in _FUNC.finditer(inv.text(p)):
            funcs.setdefault(m.group(1) or m.group(2), inv.line_at(p, m.start()))
        rest = collections.defaultdict(list)
        for name, line in funcs.items():
            w = _words(name)
            for i, word in enumerate(w):
                if word in BACKENDS:
                    rest[tuple(w[:i] + w[i + 1:])].append((name, line, word))
        for members in rest.values():
            if len({word for _, _, word in members}) >= 2:
                names = tuple(sorted(n for n, _, _ in members))
                family[names].append((p, min(line for _, line, _ in members)))
    leads = []
    for names, files in sorted(family.items(), key=lambda kv: -len(kv[1])):
        shown = ", ".join(f"`{n}`" for n in names)
        where = f"in {len(files)} files" if len(files) > 1 else "in one file"
        detail = (f"{shown} {where}: one behavior written once per backend. Each pair must return the same "
                  "columns, rows and order for the same input"
                  + (", which makes it a convention seam over the family." if len(files) > 1 else "."))
        leads.append(Lead("twin", [(p, line, None) for p, line in files[:12]], detail,
                          score=round(1.5 + min(len(files), 20) / 20, 2), extra={"signal": "branch", "files": len(files)}))
    return leads


def find(inv):
    code = [p for p in inv.read if kind_of(p) == "code" and not is_test(p)]
    return _pattern_twins(inv, code) + _language_twins(inv, code) + _backend_twins(inv, code) + _branch_twins(inv, code)
