import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from sessionvault import backup, importer, memindex
from sessionvault.cli import main
from sessionvault.config import DEFAULTS
from sessionvault.vault import long_path

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SID = "11111111-2222-3333-4444-555555555555"
SID2 = "99999999-2222-3333-4444-555555555555"


def tool_use(tid, name, file_path, sid=SID, when="2026-09-01T00:00:00.000Z"):
    return json.dumps({"type": "assistant", "uuid": tid + "-u", "sessionId": sid, "timestamp": when,
                       "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": tid, "name": name, "input": {"file_path": file_path}}]}},
                      separators=(",", ":")) + "\n"


def tool_error(tid):
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": True, "content": "failed"}]}},
        separators=(",", ":")) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.src = self.root / "projects"
        self.vault = self.root / "vault"
        self.proj = self.src / "C--work-demo"
        self.proj.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(long_path(self.root))
        self.tmp.cleanup()

    def write(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(self.root / "none.json"), "--src", str(self.src),
                         "--vault", str(self.vault), *argv])
        return code, out.getvalue(), err.getvalue()


class ImportTest(Base):
    def test_new_same_and_different(self):
        self.write(self.proj / f"{SID}.jsonl", "a\n")
        backup.run(self.src, self.vault, DEFAULTS, T0)
        archive = self.root / "archive"
        # Viewer の archive は大文字・小文字の違う綴りで持っていることがある
        self.write(archive / "c--work-demo" / f"{SID}.jsonl", "X\nold-b\n")
        self.write(archive / "c--work-demo" / f"{SID2}.jsonl", "x\n")
        self.write(archive / "C--other" / f"{SID}.jsonl", "a\n")
        r = importer.run(archive, self.src, self.vault, T0)
        self.assertEqual(r.counts, {"generation": 1, "new": 2})
        mirror = long_path(self.vault / "mirror")
        self.assertEqual((mirror / "C--work-demo" / f"{SID}.jsonl").read_text(encoding="utf-8"), "a\n")  # mirror は変えない
        self.assertTrue((mirror / "C--work-demo" / f"{SID2}.jsonl").is_file())
        [gen] = [p for p in long_path(self.vault / "generations").rglob("*") if p.is_file()]
        self.assertEqual(gen.read_text(encoding="utf-8"), "X\nold-b\n")
        self.assertEqual(importer.run(archive, self.src, self.vault, T0).counts, {"same": 2, "generation": 1})

    def test_prefix_relations_do_not_make_generations(self):
        self.write(self.proj / f"{SID}.jsonl", "a\nb\n")
        self.write(self.proj / f"{SID2}.jsonl", "a\n")
        backup.run(self.src, self.vault, DEFAULTS, T0)
        archive = self.root / "archive"
        self.write(archive / "C--work-demo" / f"{SID}.jsonl", "a\n")          # 古い
        self.write(archive / "C--work-demo" / f"{SID2}.jsonl", "a\nb\nc\n")   # 先まである
        self.assertEqual(importer.run(archive, self.src, self.vault, T0).counts, {"older": 1, "grow": 1})
        mirror = long_path(self.vault / "mirror" / "C--work-demo")
        self.assertEqual((mirror / f"{SID2}.jsonl").read_text(encoding="utf-8"), "a\nb\nc\n")
        self.assertFalse(long_path(self.vault / "generations").exists())

    def test_cli(self):
        archive = self.root / "archive"
        self.write(archive / "C--x" / f"{SID}.jsonl", "a\n")
        code, out, _ = self.cli("import", str(archive))
        self.assertEqual(code, 0)
        self.assertIn("new 1", out)


class MemoryIndexTest(Base):
    def mem(self, name, project="c--work-demo"):
        return f"C:\\Users\\u\\.claude\\projects\\{project}\\memory\\{name}"

    def test_index_writes_by_memory_file(self):
        self.write(self.proj / "memory" / "note.md", "x")
        self.write(self.proj / f"{SID}.jsonl",
                   tool_use("t1", "Write", self.mem("note.md"), when="2026-09-01T00:00:00Z")
                   + tool_use("t2", "Read", self.mem("note.md"))           # 読んだだけは数えない
                   + tool_use("t3", "Write", "C:\\work\\memory\\x.md")       # projects の外は数えない
                   + tool_use("t4", "Edit", self.mem("gone.md")) + tool_error("t4"))
        self.write(self.proj / SID2 / "subagents" / "agent-a.jsonl",
                   tool_use("t5", "Edit", self.mem("note.md"), sid=SID2, when="2026-08-01T00:00:00Z"))
        index = memindex.build(self.src, None, T0)["memory"]
        # memory フォルダの綴り（C--）に寄せる
        self.assertEqual(sorted(index), ["C--work-demo/memory/gone.md", "C--work-demo/memory/note.md"])
        note = index["C--work-demo/memory/note.md"]
        self.assertTrue(note["exists"])
        self.assertEqual([(w["session"], w["tool"], w["subagent"]) for w in note["writes"]],
                         [(SID2, "Edit", True), (SID, "Write", False)])  # 時刻順
        gone = index["C--work-demo/memory/gone.md"]
        self.assertFalse(gone["exists"])
        self.assertEqual([w["ok"] for w in gone["writes"]], [False])

    def test_mirror_keeps_deleted_sessions_and_dedupes(self):
        self.write(self.proj / f"{SID}.jsonl", tool_use("t1", "Write", self.mem("n.md")))
        self.write(self.proj / f"{SID2}.jsonl", tool_use("t2", "Edit", self.mem("n.md"), sid=SID2))
        backup.run(self.src, self.vault, DEFAULTS, T0)
        (self.proj / f"{SID2}.jsonl").unlink()
        code, out, _ = self.cli("memory-index")
        self.assertEqual(code, 0, out)
        with open(long_path(self.vault / "index" / "memory.json"), encoding="utf-8") as f:
            index = json.load(f)["memory"]
        writes = index["C--work-demo/memory/n.md"]["writes"]
        self.assertEqual(sorted(w["session"] for w in writes), [SID, SID2])  # t1 は mirror と src の両方にあるが 1 回


if __name__ == "__main__":
    unittest.main()
