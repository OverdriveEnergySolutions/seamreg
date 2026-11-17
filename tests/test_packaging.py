"""Packaging: build files against the manifests and the files the app reads."""
from __future__ import annotations

import json

from seams import split
from seams.scan import inventory, packaging

DOCKERFILE = '''ARG NODE_IMAGE_VERSION="22-alpine"
FROM node:${NODE_IMAGE_VERSION} AS builder
WORKDIR /app
COPY . .
RUN npm run build

FROM node:${NODE_IMAGE_VERSION} AS runner
ARG ORM_VERSION="5.1.0"
RUN npm install -g ormcli@${ORM_VERSION} other-tool@2.0.0
COPY --from=builder /app/orm ./orm
COPY --from=builder /app/public ./public
CMD ["npm", "start"]
'''


def repo(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return inventory.Inventory(tmp_path)


def base(tmp_path, pkg="^6.0.0", **extra):
    files = {"Dockerfile": DOCKERFILE, "package.json": json.dumps({"dependencies": {"ormcli": pkg}}),
             "orm.config.ts": "export default {}\n", "orm/schema.sql": "x\n", "public/x.js": "x\n"}
    files.update(extra)
    return packaging.find(repo(tmp_path, files))


def test_a_pinned_version_that_lags_the_manifest(tmp_path):
    [pin] = [l for l in base(tmp_path) if l.extra["signal"] == "pin"]
    assert pin.extra["package"] == "ormcli" and "5.1.0 (ARG ORM_VERSION)" in pin.detail and "differ now" in pin.detail


def test_an_agreeing_pin_is_still_a_seam_but_weaker(tmp_path):
    [pin] = [l for l in base(tmp_path, pkg="^5.1.0") if l.extra["signal"] == "pin"]
    assert "differ now" not in pin.detail and pin.score < 2


def test_a_root_file_named_like_a_copied_folder_but_not_copied(tmp_path):
    [rt] = [l for l in base(tmp_path) if l.extra["signal"] == "runtime"]
    assert rt.extra["file"] == "orm.config.ts" and "/app/orm" in rt.detail


def test_engine_versions_across_files(tmp_path):
    leads = base(tmp_path, **{".nvmrc": "20\n", ".github/workflows/ci.yml": "      node-version: '22'\n"})
    [eng] = [l for l in leads if l.extra["signal"] == "engine"]
    assert "different major versions" in eng.detail and ".nvmrc 20" in eng.detail


def test_go_version_from_go_mod(tmp_path):
    leads = packaging.find(repo(tmp_path, {"Dockerfile": "FROM golang:1.24-alpine AS b\nFROM alpine\n",
                                           "go.mod": "module x\n\ngo 1.25\n"}))
    [eng] = [l for l in leads if l.extra["signal"] == "engine"]
    assert eng.extra["runtime"] == "go"


def test_a_repo_with_no_build_files_has_no_leads(tmp_path):
    assert packaging.find(repo(tmp_path, {"src/app.py": "x = 1\n"})) == []


def test_the_focus_brief_is_generic():
    text = split.FOCUS["packaging"]["text"].lower()
    for word in ("prisma", "umami", "netbox", "memos", "kuma", "frigate"):
        assert word not in text


def test_from_flags_and_ci_env_versions(tmp_path):
    leads = packaging.find(repo(tmp_path, {
        "Dockerfile": "FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS b\nFROM alpine\n",
        ".github/workflows/ci.yml": "env:\n  GO_VERSION: 1.25.1\njobs:\n  t:\n    steps:\n      - with:\n          go-version: ${{ env.GO_VERSION }}\n"}))
    [eng] = [l for l in leads if l.extra["signal"] == "engine"]
    assert "Dockerfile 1.26-alpine" in eng.detail and "ci.yml 1.25.1" in eng.detail
