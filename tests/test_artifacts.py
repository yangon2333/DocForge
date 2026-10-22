"""工件仓库与事件流的单元测试。"""

from __future__ import annotations

import json
import unittest

from tests.fixtures import tempdir

from docforge import ArtifactStore, EventLog, MissingArtifact


class ArtifactStoreTest(unittest.TestCase):
    def test_put_and_get(self):
        store = ArtifactStore()
        store.put("scan", {"count": 2}, creator="scan")
        self.assertEqual(store.payload("scan")["count"], 2)
        self.assertTrue(store.has("scan"))
        self.assertIn("scan", store.keys())

    def test_versions_increase(self):
        store = ArtifactStore()
        store.put("draft", {"round": 1}, creator="write")
        store.put("draft", {"round": 2}, creator="write")
        self.assertEqual(store.get("draft").version, 2)
        self.assertEqual(store.versions("draft"), [1, 2])
        self.assertEqual(store.payload("draft")["round"], 2)

    def test_missing_artifact_raises(self):
        store = ArtifactStore()
        with self.assertRaises(MissingArtifact):
            store.get("nope")
        self.assertIsNone(store.maybe("nope"))
        self.assertEqual(store.maybe("nope", 42), 42)

    def test_prefix_and_filter(self):
        store = ArtifactStore()
        store.put("module:a", 1, creator="analyze")
        store.put("module:b", 2, creator="analyze")
        store.put("catalog", 3, creator="catalog")
        self.assertEqual(len(store.with_prefix("module:")), 2)
        self.assertEqual([item.payload for item in store.with_prefix("module:")], [1, 2])

    def test_dump_and_reload_latest_version(self):
        tmp = tempdir()
        dump = tmp / "artifacts"
        store = ArtifactStore(dump_dir=dump)
        store.put("draft", {"round": 1}, creator="write")
        store.put("draft", {"round": 2}, creator="write")
        store.put("scan", {"count": 4}, creator="scan")

        restored = ArtifactStore.load(dump)
        self.assertEqual(restored.payload("draft")["round"], 2, "应恢复最新版本")
        self.assertEqual(restored.payload("scan")["count"], 4)
        self.assertEqual(len(restored), 2)

    def test_dumped_file_is_valid_json(self):
        tmp = tempdir()
        dump = tmp / "artifacts"
        store = ArtifactStore(dump_dir=dump)
        store.put("module:a.b", {"module": "a.b"}, creator="analyze")
        files = list(dump.glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "module:a.b")
        self.assertEqual(data["payload"]["module"], "a.b")


class EventLogTest(unittest.TestCase):
    def test_sinks_and_jsonl(self):
        tmp = tempdir()
        path = tmp / "events.jsonl"
        log = EventLog(jsonl_path=path)
        seen = []
        log.subscribe(seen.append)
        log.emit("stage_start", "开始", stage="scan")
        log.emit("stage_done", "结束", stage="scan", elapsed=0.01)

        self.assertEqual(len(seen), 2)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["kind"], "stage_start")

    def test_sink_error_does_not_break_logging(self):
        log = EventLog()

        def boom(_event):
            raise RuntimeError("订阅者坏了")

        log.subscribe(boom)
        log.emit("warn", "仍然要记录")
        self.assertEqual(len(log.events), 1)

    def test_kinds_and_warnings(self):
        log = EventLog()
        log.emit("stage_done", "ok")
        log.emit("retry", "再试一次")
        log.emit("guard", "到达上限")
        self.assertEqual(log.kinds()["stage_done"], 1)
        self.assertEqual(len(log.warnings()), 2)


if __name__ == "__main__":
    unittest.main()
