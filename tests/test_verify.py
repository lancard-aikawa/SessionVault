import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from sessionvault import backup, verify
from sessionvault.cli import main
from sessionvault.config import DEFAULTS
from sessionvault.vault import long_path

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SID = "11111111-2222-3333-4444-555555555555"
SID2 = "99999999-2222-3333-4444-555555555555"


def rec(uuid, parent=None, **kw):
    return json.dumps({"type": "user", "uuid": uuid, "parentUuid": parent, **kw}) + "\n"


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.src = root / "projects"
        self.vault = root / "vault"
        self.proj = self.src / "C--work-demo"
        self.proj.mkdir(parents=True)
        self.session = self.proj / f"{SID}.jsonl"

    def tearDown(self):
        shutil.rmtree(long_path(Path(self.tmp.name)))
        self.tmp.cleanup()

    def write(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def checks(self, **kw):
        return [(f.check, f.severity, f.line) for f in verify.run(self.src, kw.pop("vault", None), **kw)]

    def test_clean_session(self):
        self.write(self.session, rec("a") + rec("b", "a") + json.dumps({"type": "ai-title", "title": "x"}) + "\n")
        self.assertEqual(self.checks(), [])

    def test_bad_json_in_the_middle(self):
        self.write(self.session, rec("a") + "{broken\n" + rec("b", "a"))
        self.assertEqual(self.checks(), [("bad-json", "error", 2)])

    def test_truncated_tail_is_not_also_no_newline(self):
        self.write(self.session, rec("a") + '{"type": "us')
        self.assertEqual(self.checks(), [("truncated-tail", "warning", 2)])

    def test_bad_last_line_with_newline_is_bad_json(self):
        self.write(self.session, rec("a") + "{x\n")
        self.assertEqual(self.checks(), [("bad-json", "error", 2)])

    def test_no_newline(self):
        self.write(self.session, rec("a") + rec("b", "a").rstrip("\n"))
        self.assertEqual(self.checks(), [("no-newline", "warning", 2)])

    def test_dangling_parent_and_duplicate(self):
        self.write(self.session, rec("a") + rec("b", "zzz") + rec("a"))
        self.assertEqual(self.checks(), [("dangling-parent", "error", 2), ("duplicate-uuid", "warning", 3)])

    def test_parent_may_be_in_subagent_of_same_session(self):
        self.write(self.session, rec("a", "s1"))
        self.write(self.proj / SID / "subagents" / "agent-x.jsonl", rec("s1", "a"))
        self.assertEqual(self.checks(), [])
        # 別のセッションの uuid では親にならない
        self.write(self.proj / f"{SID2}.jsonl", rec("c", "s1"))
        self.assertEqual(self.checks(), [("dangling-parent", "error", 1)])

    def test_mirror_checks(self):
        self.write(self.session, rec("a") + rec("b", "a"))
        self.write(self.proj / f"{SID2}.jsonl", rec("x"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        self.write(self.session, rec("a") + rec("c", "a") + rec("d", "c"))  # 長いが先頭が違う
        (self.proj / f"{SID2}.jsonl").unlink()
        found = verify.run(self.src, self.vault)
        self.assertEqual([(f.check, f.session) for f in found], [("diverged", SID), ("src-missing", SID2)])

    def test_growth_and_partial_tail_are_not_diverged(self):
        self.write(self.session, rec("a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        self.write(self.session, rec("a") + rec("b", "a") + '{"par')
        self.assertEqual(self.checks(vault=self.vault), [("truncated-tail", "warning", 3)])

    def test_shrunk_is_diverged(self):
        self.write(self.session, rec("a") + rec("b", "a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        self.write(self.session, rec("a"))
        self.assertEqual(self.checks(vault=self.vault), [("diverged", "error", None)])

    def test_session_filter(self):
        self.write(self.session, "{bad\n")
        self.write(self.proj / f"{SID2}.jsonl", "{bad\n")
        self.write(self.proj / SID2 / "subagents" / "agent-y.jsonl", "{bad\n")
        self.assertEqual({f.path for f in verify.run(self.src, session=SID2.upper())},
                         {f"{SID2}.jsonl", f"{SID2}/subagents/agent-y.jsonl"})

    def test_missing_vault_is_fine(self):
        self.write(self.session, rec("a"))
        self.assertEqual(self.checks(vault=self.vault), [])
        self.assertFalse(self.vault.exists())  # verify は何も作らない

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(Path(self.tmp.name) / "none.json"), "--src", str(self.src),
                         "--vault", str(self.vault), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_cli_json_and_exit_codes(self):
        self.write(self.session, rec("a") + rec("a"))
        code, out, _ = self.run_cli("verify", "--json")
        self.assertEqual(code, 0)  # 警告だけなら 0
        self.assertTrue(out.isascii())
        [item] = json.loads(out)
        self.assertEqual(set(item), {"session", "project", "path", "check", "severity", "line", "detail"})
        self.write(self.session, "{bad\n")
        code, out, err = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("bad-json", out)
        self.assertIn("error 1", err)


if __name__ == "__main__":
    unittest.main()
