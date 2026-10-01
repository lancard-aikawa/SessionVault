import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sessionvault import backup, restore, verify
from sessionvault.cli import main
from sessionvault.config import DEFAULTS
from sessionvault.repair import repair_bytes
from sessionvault.vault import long_path, ts

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SID = "11111111-2222-3333-4444-555555555555"


def rec(uuid, parent=None, **kw):
    return json.dumps({"type": "user", "uuid": uuid, "parentUuid": parent, **kw}) + "\n"


class RepairBytesTest(unittest.TestCase):
    def test_clean_is_untouched(self):
        data = (rec("a") + rec("b", "a")).encode()
        r = repair_bytes(data)
        self.assertFalse(r.changed)
        self.assertEqual(r.data, data)

    def test_truncated_tail_dropped(self):
        r = repair_bytes((rec("a") + '{"type":"user","uuid":"b","par').encode())
        self.assertEqual(r.data, rec("a").encode())
        self.assertEqual([n for n, _ in r.notes], [2])

    def test_missing_newline_added(self):
        r = repair_bytes(rec("a").rstrip("\n").encode())
        self.assertEqual(r.data, rec("a").encode())
        self.assertTrue(r.changed)

    def test_bad_middle_line_children_reattached(self):
        # b が壊れている。uuid と親は読めるので、c の親を a につなぎ直す
        broken = '{"type":"user","uuid":"b","parentUuid":"a","message":{"content":"x' + "\n"
        untouched = rec("d", "c", note="日本語")
        r = repair_bytes((rec("a") + broken + rec("c", "b", note="日本語") + untouched).encode("utf-8"))
        lines = r.data.decode("utf-8").splitlines(keepends=True)
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[1])["parentUuid"], "a")
        self.assertEqual(json.loads(lines[1])["note"], "日本語")
        self.assertEqual(lines[2], untouched)  # 手を入れない行はそのまま

    def test_consecutive_broken_lines_are_followed(self):
        b = '{"uuid":"b","parentUuid":"a","x":' + "\n"
        c = '{"uuid":"c","parentUuid":"b","x":' + "\n"
        r = repair_bytes((rec("a") + b + c + rec("d", "c")).encode())
        self.assertEqual(json.loads(r.data.splitlines()[1])["parentUuid"], "a")

    def test_broken_root_line_makes_child_root(self):
        b = '{"uuid":"b","parentUuid":null,"x":' + "\n"
        r = repair_bytes((b + rec("c", "b")).encode())
        self.assertIsNone(json.loads(r.data)["parentUuid"])

    def test_uuid_lost_in_cut_is_inferred_from_next_orphan(self):
        # 実際の行は parentUuid が先頭、uuid が後ろ。後半が欠けると uuid が読めない（2026-10-01 に実データで確認）
        b = '{"parentUuid":"a","isSidechain":false,"message":{"content":"x' + "\n"
        r = repair_bytes((rec("a") + b + rec("c", "b") + rec("d", "c")).encode())
        parents = [json.loads(x)["parentUuid"] for x in r.data.splitlines()]
        self.assertEqual(parents, [None, "a", "c"])

    def test_inference_skips_parents_known_in_subagents(self):
        b = '{"parentUuid":"a","message":{"content":"x' + "\n"
        data = (rec("a") + b + rec("c", "s1") + rec("d", "b")).encode()
        r = repair_bytes(data, frozenset({"s1"}))
        parents = [json.loads(x)["parentUuid"] for x in r.data.splitlines()]
        self.assertEqual(parents, [None, "s1", "a"])

    def test_nested_uuid_text_is_not_taken(self):
        # 壊れた行の中身に "uuid" という文字列が入っていても、エスケープされたものは拾わない
        b = '{"message":"say \\"uuid\\":\\"zzz\\"","uuid":"b","parentUuid":"a","x":' + "\n"
        r = repair_bytes((rec("a") + b + rec("c", "b")).encode())
        self.assertEqual(json.loads(r.data.splitlines()[1])["parentUuid"], "a")


class RepairRestoreCliTest(unittest.TestCase):
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

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(Path(self.tmp.name) / "none.json"), "--src", str(self.src),
                         "--vault", str(self.vault), *argv])
        return code, out.getvalue(), err.getvalue()

    def gens(self):
        return sorted(p.name for p in long_path(self.vault / "generations").rglob("*") if p.is_file())

    def test_repair_out_does_not_touch_source(self):
        broken = rec("a") + "{bad\n" + rec("b", "a")
        self.write(self.session, broken)
        out = Path(self.tmp.name) / "fixed.jsonl"
        code, stdout, _ = self.cli("repair", SID.upper(), "--out", str(out))
        self.assertEqual(code, 0)
        self.assertIn("2 行目", stdout)
        self.assertEqual(out.read_text(encoding="utf-8"), rec("a") + rec("b", "a"))
        self.assertEqual(self.session.read_text(encoding="utf-8"), broken)
        self.assertFalse(self.vault.exists())

    def test_repair_in_place_keeps_original_bytes(self):
        broken = rec("a") + "{bad\n" + rec("b", "a") + '{"tail'
        self.write(self.session, broken)
        code, _, err = self.cli("repair", SID, "--in-place")
        self.assertEqual(code, 0, err)
        self.assertIn("Claude Code で開いていない", err)
        self.assertEqual(self.session.read_text(encoding="utf-8"), rec("a") + rec("b", "a"))
        [stashed] = [p for p in long_path(self.vault / "generations").rglob("*") if p.is_file()]
        self.assertEqual(stashed.read_text(encoding="utf-8"), broken)
        self.assertEqual(verify.run(self.src), [])

    def test_repair_in_place_without_problems_writes_nothing(self):
        self.write(self.session, rec("a"))
        code, _, err = self.cli("repair", SID, "--in-place")
        self.assertEqual(code, 0)
        self.assertIn("直すところはありません", err)
        self.assertFalse(self.vault.exists())

    def test_repair_unknown_session(self):
        self.assertEqual(self.cli("repair", "nope", "--out", "x")[0], 2)

    def test_restore_deleted_session_with_subagents(self):
        self.write(self.session, rec("a"))
        self.write(self.proj / SID / "subagents" / "agent-x.jsonl", rec("s", "a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        shutil.rmtree(self.proj)
        code, out, err = self.cli("restore", SID)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.session.read_text(encoding="utf-8"), rec("a"))
        self.assertTrue((self.proj / SID / "subagents" / "agent-x.jsonl").is_file())
        self.assertEqual(self.gens(), [])  # 上書きしたものが無いので世代は増えない

    def test_restore_generation_stashes_current_source(self):
        self.write(self.session, rec("a") + rec("b", "a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        good = self.session.read_bytes()
        self.write(self.session, rec("a"))  # 縮んだ
        backup.run(self.src, self.vault, DEFAULTS, T0 + timedelta(hours=1))
        code, out, _ = self.cli("restore", SID, "--list")
        self.assertEqual(code, 0)
        stamp = ts(T0 + timedelta(hours=1))
        self.assertIn(stamp, out)
        self.write(self.session, rec("a") + rec("z", "a"))  # 今の中身（これも残す）
        done = restore.run(self.src, self.vault, SID, stamp, T0 + timedelta(hours=2))
        self.assertEqual([(d.rel, d.action) for d in done], [(f"{SID}.jsonl", "restored")])
        self.assertEqual(self.session.read_bytes(), good)
        self.assertEqual(done[0].stashed.read_text(encoding="utf-8"), rec("a") + rec("z", "a"))

    def test_restore_same_content_is_noop(self):
        self.write(self.session, rec("a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        done = restore.run(self.src, self.vault, SID)
        self.assertEqual([d.action for d in done], ["same"])

    def test_restore_errors(self):
        self.assertEqual(self.cli("restore", SID)[0], 2)
        self.write(self.session, rec("a"))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        code, _, err = self.cli("restore", SID, "--generation", "20000101T000000Z")
        self.assertEqual(code, 2)
        self.assertIn("ありません", err)


if __name__ == "__main__":
    unittest.main()
