"""SQLite 저장소 + 되돌릴 수 있는 마이그레이션 (up/down).

Supabase 로 옮길 때도 같은 SQL 을 쓸 수 있도록 표준 SQL 위주로 작성.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"
STEP_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "RETRY")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str | Path = "data/shorts.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT)")
        self.migrate()

    # ------------------------------------------------------------ migrations
    def _versions(self) -> list[str]:
        return sorted(p.name.split(".")[0] for p in MIGRATIONS.glob("*.up.sql"))

    def applied(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT version FROM schema_migrations ORDER BY version")]

    def migrate(self) -> list[str]:
        done = set(self.applied())
        new = []
        with self.lock:
            for v in self._versions():
                if v in done:
                    continue
                self.conn.executescript((MIGRATIONS / f"{v}.up.sql").read_text(encoding="utf-8"))
                self.conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (v, now()))
                self.conn.commit()
                new.append(v)
        return new

    def rollback(self) -> str | None:
        """가장 최근 마이그레이션 하나를 되돌린다."""
        applied = self.applied()
        if not applied:
            return None
        v = applied[-1]
        with self.lock:
            self.conn.executescript((MIGRATIONS / f"{v}.down.sql").read_text(encoding="utf-8"))
            self.conn.execute("DELETE FROM schema_migrations WHERE version = ?", (v,))
            self.conn.commit()
        return v

    # ------------------------------------------------------------ helpers
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params)]

    # ------------------------------------------------------------ jobs
    def create_job(self, job_id: str, mode: str, product_name: str, inputs: dict) -> None:
        t = now()
        self.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                     (job_id, mode, "PENDING", product_name, json.dumps(inputs, ensure_ascii=False), None, 0, t, t))

    def update_job(self, job_id: str, status: str, result: dict | None = None) -> None:
        total = self.job_cost(job_id)
        self.execute("UPDATE jobs SET status=?, result_json=COALESCE(?, result_json), total_cost=?, updated_at=? WHERE id=?",
                     (status, json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                      total, now(), job_id))

    def step(self, job_id: str, step: str, status: str, detail: str = "", attempt: int = 0) -> None:
        assert status in STEP_STATUSES
        t = now()
        if status == "RUNNING":
            self.execute("INSERT INTO job_steps (job_id, step, status, attempt, detail, started_at) VALUES (?,?,?,?,?,?)",
                         (job_id, step, status, attempt, detail, t))
        else:
            self.execute("""UPDATE job_steps SET status=?, detail=?, finished_at=? WHERE id =
                            (SELECT MAX(id) FROM job_steps WHERE job_id=? AND step=?)""",
                         (status, detail[:2000], t, job_id, step))

    def steps(self, job_id: str) -> list[dict]:
        return self.query("SELECT step, status, attempt, detail, started_at, finished_at FROM job_steps "
                          "WHERE job_id=? ORDER BY id", (job_id,))

    # ------------------------------------------------------------ cost / qa / assets
    def add_cost(self, job_id: str | None, provider: str, model: str, task: str,
                 input_usage: float, output_usage: float, cost: float, duration: float) -> None:
        self.execute("INSERT INTO costs (job_id, provider, model, task, input_usage, output_usage, "
                     "estimated_cost, duration, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                     (job_id, provider, model, task, input_usage, output_usage, cost, duration, now()))

    def job_cost(self, job_id: str) -> float:
        r = self.query("SELECT COALESCE(SUM(estimated_cost),0) AS c FROM costs WHERE job_id=?", (job_id,))
        return round(r[0]["c"], 5)

    def add_qa(self, job_id: str, stage: str, target: str, scores: dict, passed: bool, notes: str = "") -> None:
        self.execute("INSERT INTO qa_results (job_id, stage, target, scores_json, passed, notes, timestamp) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (job_id, stage, target, json.dumps(scores, ensure_ascii=False), int(passed), notes, now()))

    def add_asset(self, job_id: str, path: str, kind: str, rights: str, source: str = "") -> None:
        self.execute("INSERT INTO assets (job_id, path, kind, rights, source) VALUES (?,?,?,?,?)",
                     (job_id, path, kind, rights, source))

    def job(self, job_id: str) -> dict | None:
        rows = self.query("SELECT * FROM jobs WHERE id=?", (job_id,))
        return rows[0] if rows else None
