"""Packaging: what the image or the build ships against what the code and its manifests say.

Three signals, each a seam between a build file and the rest of the repo:

- pin: a package version written into a Dockerfile (`ARG PRISMA_VERSION="6.19.0"` used as
  `prisma@${PRISMA_VERSION}`, or `pip install x==1.2`) and the same package in a manifest
  (package.json, requirements, pyproject). They drift when a dependency bump skips the image.
- runtime: the final stage of a multi-stage Dockerfile copies some files from the build stage
  by name. A file at the repo root that shares a name with one of them (prisma/ and
  prisma.config.ts) and is not copied is often a file the app reads at run time.
- engine: one runtime version (node, python, go) stated in more than one place: a Dockerfile's
  FROM, a CI setup step, .nvmrc or .python-version, package.json engines.
"""
from __future__ import annotations

import json
import re

from seams.scan.inventory import Lead

_ARG = re.compile(r"^\s*ARG\s+(\w+)\s*=\s*\"?([\w.\-]+)\"?", re.M)
_PKG_AT = re.compile(r"(?<![\w/])((?:@[\w.-]+/)?[\w.-]+)@(\$\{?\w+\}?|\d[\w.\-]*)")
_PIP = re.compile(r"\bpip3?\s+install\b[^\n]*")
_PIP_PIN = re.compile(r"\b([A-Za-z][\w.\-]*)==(\d[\w.\-]*)")
_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\w+))?", re.M | re.I)
_COPY_FROM = re.compile(r"^\s*COPY\s+(?:--\S+\s+)*--from=(\w+)\s+(?:--\S+\s+)*(\S+)\s+\S+", re.M | re.I)
_VER = re.compile(r"(\d+)(?:\.(\d+))?")


def _major_minor(v):
    m = _VER.search(v or "")
    return (m.group(1), m.group(2)) if m else None


def _dockerfiles(inv):
    return [p for p in inv.read if p.rsplit("/", 1)[-1].startswith("Dockerfile") or p.endswith(".dockerfile")]


def _manifest_versions(inv):
    """{package: (path, version text)} from package.json files and Python requirement files."""
    out = {}
    for p in inv.read:
        name = p.rsplit("/", 1)[-1]
        text = inv.text(p)
        if name == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                for pkg, ver in (data.get(key) or {}).items():
                    if isinstance(ver, str):
                        out.setdefault(pkg, (p, ver))
        elif name.endswith(".txt") and "requirements" in name or name == "pyproject.toml":
            for m in re.finditer(r"^\s*\"?([A-Za-z][\w.\-]*)\s*(?:\[[^\]]*\])?\s*(==|>=|~=|\^)\s*([\d][\w.\-]*)", text, re.M):
                out.setdefault(m.group(1).lower(), (p, m.group(3)))
    return out


VERSION_FILES = {".nvmrc", ".node-version", ".python-version", "go.mod"}  # not file types the scan reads


def _text(inv, p):
    """The scan's text for a file it read, else the file itself when it is a small version file."""
    t = inv.text(p)
    if t or p.rsplit("/", 1)[-1] not in VERSION_FILES:
        return t
    try:
        f = inv.root / p
        return f.read_text(encoding="utf-8", errors="replace") if f.stat().st_size < 20000 else ""
    except OSError:
        return ""


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _pins(inv, manifests):
    leads = []
    for df in _dockerfiles(inv):
        text = inv.text(df)
        args = {m.group(1): (m.group(2), _line(text, m.start())) for m in _ARG.finditer(text)}
        for m in _PKG_AT.finditer(text):
            pkg, ver = m.group(1), m.group(2)
            if pkg.startswith(("http", "node", "python")) or pkg not in manifests:
                continue
            arg = ver.strip("${}")
            if not ver[:1].isdigit():
                if arg not in args:
                    continue
                ver, at = args[arg]
            else:
                at = _line(text, m.start())
            mp, mv = manifests[pkg]
            differ = _major_minor(ver) != _major_minor(mv)
            leads.append(Lead("packaging", [(df, at, None), (mp, None, None)],
                              f"{df} installs {pkg} at {ver}{f' (ARG {arg})' if arg != ver else ''}, and {mp} asks for "
                              f"{pkg} {mv}. A version written into the image drifts when a dependency bump skips it."
                              + (" They differ now." if differ else ""),
                              score=2.5 if differ else 1.5, extra={"signal": "pin", "package": pkg}))
        for line in _PIP.finditer(text):
            for m in _PIP_PIN.finditer(line.group(0)):
                pkg = m.group(1).lower()
                if pkg in manifests:
                    mp, mv = manifests[pkg]
                    differ = _major_minor(m.group(2)) != _major_minor(mv)
                    leads.append(Lead("packaging", [(df, _line(text, line.start()), None), (mp, None, None)],
                                      f"{df} pins {pkg}=={m.group(2)}, and {mp} asks for {pkg} {mv}."
                                      + (" They differ now." if differ else ""),
                                      score=2.5 if differ else 1.5, extra={"signal": "pin", "package": pkg}))
    return leads


def _runtime(inv):
    """Root files that share a name with what the final stage copies, and are not copied."""
    root_files = {p for p in inv.files if "/" not in p}
    root_dirs = {p.split("/", 1)[0] for p in inv.files if "/" in p}
    leads = []
    for df in _dockerfiles(inv):
        text = inv.text(df)
        stages = [(m.start(), m.group(2)) for m in _FROM.finditer(text)]
        if len(stages) < 2:
            continue
        final = stages[-1][0]
        copied = [(m.group(2), _line(text, m.start())) for m in _COPY_FROM.finditer(text) if m.start() > final]
        if not copied:
            continue
        names = {c.strip("./").split("/")[-1].lower() for c, _ in copied if c.strip("./")}
        names = {n.split("/")[-1] for n in names} | {c.strip("./").split("/")[1].lower() for c, _ in copied
                                                     if c.strip("./").count("/") >= 1 and c.startswith("/app/")}
        for f in sorted(root_files):
            stem = f.split(".", 1)[0].lower()
            if not stem or f.lower() in names or stem in ("readme", "license", "dockerfile", "package", "tsconfig"):
                continue
            hit = [c for c, _ in copied if stem and (stem in c.lower().split("/")) and f.lower() not in c.lower()]
            if hit and stem in root_dirs | {n for n in names}:
                line = next(l for c, l in copied if c in hit)
                leads.append(Lead("packaging", [(df, line, None), (f, None, None)],
                                  f"The final stage of {df} copies {', '.join(hit[:3])} from an earlier stage, but not "
                                  f"{f}, which sits beside it and shares its name. If the app or a tool it runs reads "
                                  f"{f} at run time, the image lacks it.",
                                  score=2.0, extra={"signal": "runtime", "file": f}))
    return leads


def _engines(inv):
    """One runtime's version stated in more than one place."""
    seen = {}  # runtime -> [(path, line, version)]

    def add(rt, path, line, ver):
        if _major_minor(ver):
            seen.setdefault(rt, []).append((path, line, ver))

    for df in _dockerfiles(inv):
        text = inv.text(df)
        args = {m.group(1): m.group(2) for m in _ARG.finditer(text)}
        for m in _FROM.finditer(text):
            img = m.group(1)
            for rt in ("node", "python", "golang"):
                if img.startswith(rt + ":"):
                    tag = img.split(":", 1)[1]
                    tag = re.sub(r"\$\{?(\w+)\}?", lambda a: args.get(a.group(1), a.group(0)), tag)
                    add("go" if rt == "golang" else rt, df, _line(text, m.start()), tag)
    for p in sorted(set(inv.read) | {f for f in inv.files if f.rsplit("/", 1)[-1] in VERSION_FILES}):
        name = p.rsplit("/", 1)[-1]
        text = _text(inv, p)
        if name in (".nvmrc", ".node-version"):
            add("node", p, 1, text.strip())
        elif name == ".python-version":
            add("python", p, 1, text.strip())
        elif name == "go.mod":
            m = re.search(r"^go\s+(\d[\w.]*)", text, re.M)
            if m:
                add("go", p, _line(text, m.start()), m.group(1))
        elif name == "package.json" and "/" not in p:
            try:
                eng = (json.loads(text).get("engines") or {}).get("node")
            except ValueError:
                eng = None
            if isinstance(eng, str):
                add("node", p, None, eng)
        elif p.startswith(".github/workflows/"):
            for m in re.finditer(r"(node|python|go)-version:\s*['\"]?(\$\{\{\s*env\.(\w+)\s*\}\}|[\w.x\-]+)", text):
                ver = m.group(2)
                if m.group(3):  # ${{ env.GO_VERSION }}: the value from the workflow's env block
                    e = re.search(rf"^\s*{m.group(3)}:\s*['\"]?([\w.x\-]+)", text, re.M)
                    if not e:
                        continue
                    ver = e.group(1)
                add(m.group(1), p, _line(text, m.start()), ver)
    leads = []
    for rt, places in seen.items():
        files = {p for p, _, _ in places}
        if len(files) < 2:
            continue
        majors = {(_major_minor(v) or ("?",))[0] for _, _, v in places}
        leads.append(Lead("packaging", [(p, l, None) for p, l, _ in places[:8]],
                          f"The {rt} version is stated in {len(files)} files: "
                          + "; ".join(f"{p} {v}" for p, _, v in places[:8])
                          + (". They name different major versions." if len(majors) > 1 else "."),
                          score=2.0 if len(majors) > 1 else 1.0, extra={"signal": "engine", "runtime": rt}))
    return leads


def find(inv):
    manifests = _manifest_versions(inv)
    return _pins(inv, manifests) + _runtime(inv) + _engines(inv)
