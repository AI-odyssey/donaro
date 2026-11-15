"""Single-server task journal. SQLite commits protect task state across restarts."""
import json
import sqlite3
import time
from contextlib import closing


class TaskStore:
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS runtime_state (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def get_state(self, key, default=None):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT payload FROM runtime_state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO runtime_state VALUES (?, ?)",
                       (key, json.dumps(value, ensure_ascii=False)))

    scrub = staticmethod(lambda text: text)  # server가 접속 열쇠 가림 함수로 바꿔 끼운다

    def save(self, task):
        payload = {k: v for k, v in task.items() if k not in ("worker", "job")}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?)",
                       (task["id"], self.scrub(json.dumps(payload, ensure_ascii=False))))

    def load(self):
        with closing(sqlite3.connect(self.path)) as db:
            tasks = {i: json.loads(p) for i, p in db.execute("SELECT id, payload FROM tasks ORDER BY id")}
        for task in tasks.values():
            if task["status"] in ("queued", "running"):
                recoverable = task.get("phase") in ("executed", "validated") and bool(task.get("pending_result"))
                task.update(status="queued" if recoverable else "error",
                            result="저장된 결과의 검증·전달을 재개합니다." if recoverable else "서버가 재시작되어 중단됐습니다. 자동 재실행하지 않았습니다.",
                            finished=time.time())
                if not recoverable and task.get("contract", {}).get("kind") == "write":
                    task["status"] = "needs_reconciliation"
                self.save(task)
        return tasks
