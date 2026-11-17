"""The date-format finder: a named date format, and code beside its users that writes dates another way.
It finds the uptime-kuma drift two blind reviews missed: maintenance.js wrote toISOString() beside
monitor.js, which uses SQL_DATETIME_FORMAT."""
from __future__ import annotations

from seams.scan import formats
from seams.scan.inventory import Inventory


def repo(tmp_path, files):
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return Inventory(tmp_path)


def test_a_second_date_writer_beside_a_user_is_a_lead(tmp_path):
    inv = repo(tmp_path, {
        "src/util.ts": 'export const SQL_DATETIME_FORMAT = "YYYY-MM-DD HH:mm:ss";\n',
        "server/model/monitor.js": "x.format(SQL_DATETIME_FORMAT);\n",
        "server/model/maintenance.js": "a\nthis.last_start_date = current.toISOString();\n",
        "server/notify/alert.js": "new Date().toISOString();\n",  # not beside a user
    })
    [lead] = formats.find(inv)
    paths = [l[0] for l in lead.locs]
    assert lead.kind == "date-format" and paths[0] == "src/util.ts"
    assert ("server/model/maintenance.js", 2, None) in lead.locs and "server/notify/alert.js" not in paths
    assert "server/model/monitor.js" in paths and "toISOString" in lead.detail


def test_python_isoformat_beside_a_strftime_constant(tmp_path):
    inv = repo(tmp_path, {
        "app/config.py": 'DATE_FORMAT = "%Y-%m-%d %H:%M"\n',
        "app/report.py": "from app.config import DATE_FORMAT\nd.strftime(DATE_FORMAT)\n",
        "app/export.py": "row['at'] = when.isoformat()\n",
    })
    [lead] = formats.find(inv)
    assert "app/export.py" in [l[0] for l in lead.locs]


def test_no_lead_without_a_second_writer_or_for_a_non_date_format(tmp_path):
    inv = repo(tmp_path, {
        "src/util.ts": 'export const SQL_DATETIME_FORMAT = "YYYY-MM-DD";\nlet s = d.toISOString();\n',
        "src/util.js": 'exports.SQL_DATETIME_FORMAT = "YYYY-MM-DD";\nvar s = d.toISOString();\n',
        "src/a.js": "x.format(SQL_DATETIME_FORMAT);\n",
        "lib/log.js": 'const LOG_FORMAT = "[%(level)s] %(msg)s";\nnew Date().toISOString();\n',
    })
    assert formats.find(inv) == []  # util's own write and its compiled twin's do not count
