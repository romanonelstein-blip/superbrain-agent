from __future__ import annotations
import json, math, sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    question: str
    created_at: str
    updated_at: str
    final_value: str | None = None

@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    run_id: str
    claim: str
    stance: str
    source_id: str
    source_family: str
    reliability: float
    freshness: float
    relevance: float
    verified: bool
    citation: str | None = None
    content_hash: str | None = None
    retrieved_at: str | None = None
    location: str | None = None
    content_type: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    provider_agent: str | None = None
    provider_attempts: int | None = None
    provider_latency_ms: int | None = None

@dataclass(frozen=True)
class MasterDecisionRecord:
    decision_id: str
    run_id: str
    action: str
    note: str
    desired_outcome: str | None
    created_at: str

@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    namespace: str
    text: str
    metadata: dict[str, Any]
    embedding: tuple[float, ...]

@dataclass(frozen=True)
class MemoryHit:
    memory: MemoryRecord
    similarity: float

class SQLiteStateStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
          run_id TEXT PRIMARY KEY,status TEXT NOT NULL,question TEXT NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,final_value TEXT
        );
        CREATE TABLE IF NOT EXISTS evidence(
          evidence_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,claim TEXT NOT NULL,
          stance TEXT NOT NULL,source_id TEXT NOT NULL,source_family TEXT NOT NULL,
          reliability REAL NOT NULL,freshness REAL NOT NULL,relevance REAL NOT NULL,
          verified INTEGER NOT NULL,citation TEXT,content_hash TEXT,
          retrieved_at TEXT,location TEXT,content_type TEXT,
          provider TEXT,provider_model TEXT,provider_request_id TEXT,
          provider_agent TEXT,provider_attempts INTEGER,provider_latency_ms INTEGER,
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);
        CREATE TABLE IF NOT EXISTS source_reputation(
          source_id TEXT PRIMARY KEY,source_family TEXT NOT NULL,
          observations INTEGER NOT NULL DEFAULT 0,
          verified_hits INTEGER NOT NULL DEFAULT 0,
          contradiction_hits INTEGER NOT NULL DEFAULT 0,
          reliability_score REAL NOT NULL DEFAULT 0.5
        );
        CREATE TABLE IF NOT EXISTS agent_performance(
          agent_id TEXT PRIMARY KEY,runs INTEGER NOT NULL DEFAULT 0,
          accepted_evidence INTEGER NOT NULL DEFAULT 0,
          rejected_evidence INTEGER NOT NULL DEFAULT 0,
          verifier_passes INTEGER NOT NULL DEFAULT 0,
          score REAL NOT NULL DEFAULT 0.5
        );
        CREATE TABLE IF NOT EXISTS semantic_memory(
          memory_id TEXT PRIMARY KEY,namespace TEXT NOT NULL,text TEXT NOT NULL,
          metadata_json TEXT NOT NULL,embedding_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_namespace ON semantic_memory(namespace);
        CREATE TABLE IF NOT EXISTS world_beliefs(
          belief_id TEXT PRIMARY KEY,
          proposition TEXT NOT NULL,
          normalized_proposition TEXT NOT NULL,
          state TEXT NOT NULL,
          confidence REAL NOT NULL,
          support_strength REAL NOT NULL,
          challenge_strength REAL NOT NULL,
          evidence_count INTEGER NOT NULL,
          unique_source_count INTEGER NOT NULL,
          unique_family_count INTEGER NOT NULL,
          freshness REAL NOT NULL,
          last_run_id TEXT,
          first_seen_at TEXT NOT NULL,
          last_updated_at TEXT NOT NULL,
          revision_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_world_beliefs_updated
          ON world_beliefs(last_updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_world_beliefs_state
          ON world_beliefs(state);
        CREATE TABLE IF NOT EXISTS world_belief_evidence(
          belief_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          stance TEXT NOT NULL,
          added_at TEXT NOT NULL,
          PRIMARY KEY(belief_id,evidence_id),
          FOREIGN KEY(belief_id) REFERENCES world_beliefs(belief_id)
        );
        CREATE INDEX IF NOT EXISTS idx_world_belief_evidence_run
          ON world_belief_evidence(run_id);
        CREATE TABLE IF NOT EXISTS change_events(
          change_id TEXT PRIMARY KEY,
          belief_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          severity TEXT NOT NULL,
          title TEXT NOT NULL,
          detail TEXT NOT NULL,
          previous_state TEXT,
          current_state TEXT NOT NULL,
          previous_confidence REAL,
          current_confidence REAL NOT NULL,
          created_at TEXT NOT NULL,
          acknowledged INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(belief_id) REFERENCES world_beliefs(belief_id),
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_change_events_created
          ON change_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_change_events_belief
          ON change_events(belief_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS assurance_runs(
          assurance_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
          total INTEGER NOT NULL, passed INTEGER NOT NULL, failed INTEGER NOT NULL,
          inconclusive INTEGER NOT NULL, score REAL NOT NULL,
          critical_failures_json TEXT NOT NULL, cases_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_assurance_runs_created
          ON assurance_runs(created_at DESC);
        CREATE TABLE IF NOT EXISTS autonomy_cycles(
          cycle_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_autonomy_cycles_created
          ON autonomy_cycles(created_at DESC);
        CREATE TABLE IF NOT EXISTS scheduler_jobs(
          job_name TEXT PRIMARY KEY,
          enabled INTEGER NOT NULL,
          interval_seconds INTEGER NOT NULL,
          next_run_at REAL NOT NULL,
          last_run_at REAL,
          last_cycle_id TEXT,
          consecutive_failures INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_audit(
          run_id TEXT NOT NULL,event_index INTEGER NOT NULL,stage TEXT NOT NULL,
          detail TEXT NOT NULL,PRIMARY KEY(run_id,event_index),
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS master_decisions(
          decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL,
          note TEXT NOT NULL, desired_outcome TEXT, created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_master_decisions_run
          ON master_decisions(run_id, created_at);
        CREATE TRIGGER IF NOT EXISTS master_decisions_no_update
          BEFORE UPDATE ON master_decisions
          BEGIN SELECT RAISE(ABORT, 'master decisions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS master_decisions_no_delete
          BEFORE DELETE ON master_decisions
          BEGIN SELECT RAISE(ABORT, 'master decisions are append-only'); END;
        """)
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(evidence)")}
        provenance_columns = {
            "citation": "TEXT",
            "content_hash": "TEXT",
            "retrieved_at": "TEXT",
            "location": "TEXT",
            "content_type": "TEXT",
            "provider": "TEXT",
            "provider_model": "TEXT",
            "provider_request_id": "TEXT",
            "provider_agent": "TEXT",
            "provider_attempts": "INTEGER",
            "provider_latency_ms": "INTEGER",
        }
        for column, sql_type in provenance_columns.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE evidence ADD COLUMN {column} {sql_type}")
        self.conn.commit()

    def add_change_event(self, record: dict[str, Any]):
        self.conn.execute(
            "INSERT INTO change_events(change_id,belief_id,run_id,event_type,severity,title,detail,previous_state,current_state,previous_confidence,current_confidence,created_at,acknowledged) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (record["change_id"], record["belief_id"], record["run_id"], record["event_type"],
             record["severity"], record["title"], record["detail"], record.get("previous_state"),
             record["current_state"], record.get("previous_confidence"), record["current_confidence"],
             record["created_at"], int(record.get("acknowledged", False))),
        )
        self.conn.commit()

    def list_change_events(self, limit: int = 50, *, unacknowledged_only: bool = False):
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        sql = "SELECT * FROM change_events"
        params: list[Any] = []
        if unacknowledged_only:
            sql += " WHERE acknowledged=0"
        sql += " ORDER BY created_at DESC, change_id DESC LIMIT ?"
        params.append(limit)
        return tuple(dict(row) for row in self.conn.execute(sql, params).fetchall())

    def put_scheduler_job(self, record: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO scheduler_jobs(
                 job_name,enabled,interval_seconds,next_run_at,last_run_at,last_cycle_id,
                 consecutive_failures,last_error,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_name) DO UPDATE SET
                 enabled=excluded.enabled,
                 interval_seconds=excluded.interval_seconds,
                 next_run_at=excluded.next_run_at,
                 last_run_at=excluded.last_run_at,
                 last_cycle_id=excluded.last_cycle_id,
                 consecutive_failures=excluded.consecutive_failures,
                 last_error=excluded.last_error,
                 updated_at=excluded.updated_at""",
            (
                record["job_name"], int(bool(record["enabled"])), int(record["interval_seconds"]),
                float(record["next_run_at"]),
                None if record.get("last_run_at") is None else float(record["last_run_at"]),
                record.get("last_cycle_id"), int(record.get("consecutive_failures", 0)),
                record.get("last_error"), record["updated_at"],
            ),
        )
        self.conn.commit()

    def get_scheduler_job(self, job_name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM scheduler_jobs WHERE job_name=?", (job_name,)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def integrity_check(self) -> tuple[bool, str]:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        detail = str(row[0]) if row else "no result"
        return detail.lower() == "ok", detail

    def backup_to(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == Path(self.path).resolve():
            raise ValueError("backup destination must differ from the live database")
        backup = sqlite3.connect(str(target))
        try:
            self.conn.backup(backup)
            row = backup.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError(f"backup integrity check failed: {row[0] if row else 'no result'}")
        finally:
            backup.close()
        return target

    def restore_from(self, source: str | Path) -> None:
        backup_path = Path(source)
        if not backup_path.exists() or not backup_path.is_file():
            raise FileNotFoundError(str(backup_path))
        if backup_path.resolve() == Path(self.path).resolve():
            raise ValueError("restore source must differ from the live database")
        source_conn = sqlite3.connect(str(backup_path))
        try:
            row = source_conn.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError(f"restore source integrity check failed: {row[0] if row else 'no result'}")
            self.conn.commit()
            source_conn.backup(self.conn)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._migrate()
            ok, detail = self.integrity_check()
            if not ok:
                raise RuntimeError(f"restored database integrity check failed: {detail}")
        finally:
            source_conn.close()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def upsert_run(self, r: RunRecord):
        self.conn.execute("""
        INSERT INTO runs VALUES(?,?,?,?,?,?)
        ON CONFLICT(run_id) DO UPDATE SET
          status=excluded.status,question=excluded.question,
          updated_at=excluded.updated_at,final_value=excluded.final_value
        """,(r.run_id,r.status,r.question,r.created_at,r.updated_at,r.final_value))
        self.conn.commit()

    def get_run(self, run_id: str):
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?",(run_id,)).fetchone()
        return RunRecord(**dict(row)) if row else None

    def list_runs(self, limit: int = 50):
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY updated_at DESC, run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(RunRecord(**dict(row)) for row in rows)

    def put_master_decision(self, record: MasterDecisionRecord):
        self.conn.execute(
            "INSERT INTO master_decisions(decision_id,run_id,action,note,desired_outcome,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (record.decision_id, record.run_id, record.action, record.note,
             record.desired_outcome, record.created_at),
        )
        self.conn.commit()

    def list_master_decisions(self, run_id: str):
        rows = self.conn.execute(
            "SELECT * FROM master_decisions WHERE run_id=? ORDER BY created_at, decision_id",
            (run_id,),
        ).fetchall()
        return tuple(MasterDecisionRecord(**dict(row)) for row in rows)

    def replace_run_audit(self, run_id: str, events: Sequence[tuple[str, str]]):
        self.conn.execute("DELETE FROM run_audit WHERE run_id=?", (run_id,))
        self.conn.executemany(
            "INSERT INTO run_audit(run_id,event_index,stage,detail) VALUES(?,?,?,?)",
            ((run_id, index, stage, detail) for index, (stage, detail) in enumerate(events)),
        )
        self.conn.commit()

    def list_run_audit(self, run_id: str):
        rows = self.conn.execute(
            "SELECT stage,detail FROM run_audit WHERE run_id=? ORDER BY event_index",
            (run_id,),
        ).fetchall()
        return tuple((row["stage"], row["detail"]) for row in rows)

    def put_evidence(self, e: EvidenceRecord):
        self.conn.execute("""
        INSERT INTO evidence(
          evidence_id,run_id,claim,stance,source_id,source_family,
          reliability,freshness,relevance,verified,citation,content_hash,
          retrieved_at,location,content_type,provider,provider_model,
          provider_request_id,provider_agent,provider_attempts,provider_latency_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          claim=excluded.claim,stance=excluded.stance,source_id=excluded.source_id,
          source_family=excluded.source_family,reliability=excluded.reliability,
          freshness=excluded.freshness,relevance=excluded.relevance,verified=excluded.verified,
          citation=excluded.citation,content_hash=excluded.content_hash,
          retrieved_at=excluded.retrieved_at,location=excluded.location,
          content_type=excluded.content_type,provider=excluded.provider,
          provider_model=excluded.provider_model,
          provider_request_id=excluded.provider_request_id,
          provider_agent=excluded.provider_agent,
          provider_attempts=excluded.provider_attempts,
          provider_latency_ms=excluded.provider_latency_ms
        """,(e.evidence_id,e.run_id,e.claim,e.stance,e.source_id,e.source_family,
             e.reliability,e.freshness,e.relevance,int(e.verified),e.citation,
             e.content_hash,e.retrieved_at,e.location,e.content_type,e.provider,
             e.provider_model,e.provider_request_id,e.provider_agent,
             e.provider_attempts,e.provider_latency_ms))
        self.conn.commit()

    def list_evidence(self, run_id: str):
        rows=self.conn.execute("SELECT * FROM evidence WHERE run_id=? ORDER BY evidence_id",(run_id,)).fetchall()
        return tuple(EvidenceRecord(
            evidence_id=r["evidence_id"],run_id=r["run_id"],claim=r["claim"],stance=r["stance"],
            source_id=r["source_id"],source_family=r["source_family"],reliability=r["reliability"],
            freshness=r["freshness"],relevance=r["relevance"],verified=bool(r["verified"]),
            citation=r["citation"],content_hash=r["content_hash"],retrieved_at=r["retrieved_at"],
            location=r["location"],content_type=r["content_type"],provider=r["provider"],
            provider_model=r["provider_model"],provider_request_id=r["provider_request_id"],
            provider_agent=r["provider_agent"],provider_attempts=r["provider_attempts"],
            provider_latency_ms=r["provider_latency_ms"]
        ) for r in rows)

    def add_assurance_run(self, assurance_id: str, record: dict[str, Any], created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO assurance_runs(assurance_id,run_id,status,total,passed,failed,inconclusive,score,critical_failures_json,cases_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (assurance_id, record["run_id"], record["status"], record["total"], record["passed"],
             record["failed"], record["inconclusive"], record["score"], json.dumps(record["critical_failures"]),
             json.dumps(record["cases"]), created_at),
        )
        self.conn.commit()

    def list_assurance_runs(self, limit: int = 50):
        rows = self.conn.execute("SELECT * FROM assurance_runs ORDER BY created_at DESC LIMIT ?", (max(1, limit),)).fetchall()
        return tuple({**dict(r), "critical_failures": json.loads(r["critical_failures_json"]), "cases": json.loads(r["cases_json"])} for r in rows)

    def add_autonomy_cycle(self, cycle_id: str, record: dict[str, Any], created_at: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO autonomy_cycles(cycle_id,status,payload_json,created_at) VALUES(?,?,?,?)",
            (cycle_id, record["status"], json.dumps(record, sort_keys=True), created_at),
        )
        self.conn.commit()

    def list_autonomy_cycles(self, limit: int = 20):
        rows = self.conn.execute(
            "SELECT * FROM autonomy_cycles ORDER BY created_at DESC LIMIT ?", (max(1, limit),)
        ).fetchall()
        return tuple({**dict(r), "payload": json.loads(r["payload_json"])} for r in rows)

    def get_world_belief(self, belief_id: str):
        row = self.conn.execute(
            "SELECT * FROM world_beliefs WHERE belief_id=?", (belief_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_world_beliefs(self, limit: int = 100):
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        rows = self.conn.execute(
            "SELECT * FROM world_beliefs ORDER BY last_updated_at DESC, belief_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def put_world_belief(self, belief: dict[str, object]) -> None:
        self.conn.execute(
            """INSERT INTO world_beliefs(
                belief_id,proposition,normalized_proposition,state,confidence,
                support_strength,challenge_strength,evidence_count,unique_source_count,
                unique_family_count,freshness,last_run_id,first_seen_at,last_updated_at,revision_count
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(belief_id) DO UPDATE SET
              proposition=excluded.proposition,
              normalized_proposition=excluded.normalized_proposition,
              state=excluded.state,confidence=excluded.confidence,
              support_strength=excluded.support_strength,
              challenge_strength=excluded.challenge_strength,
              evidence_count=excluded.evidence_count,
              unique_source_count=excluded.unique_source_count,
              unique_family_count=excluded.unique_family_count,
              freshness=excluded.freshness,last_run_id=excluded.last_run_id,
              last_updated_at=excluded.last_updated_at,revision_count=excluded.revision_count
            """,
            (
                belief["belief_id"], belief["proposition"], belief["normalized_proposition"],
                belief["state"], belief["confidence"], belief["support_strength"],
                belief["challenge_strength"], belief["evidence_count"],
                belief["unique_source_count"], belief["unique_family_count"],
                belief["freshness"], belief.get("last_run_id"), belief["first_seen_at"],
                belief["last_updated_at"], belief["revision_count"],
            ),
        )
        self.conn.commit()

    def list_world_belief_evidence(self, belief_id: str):
        rows = self.conn.execute(
            "SELECT evidence_id,run_id,stance,added_at FROM world_belief_evidence "
            "WHERE belief_id=? ORDER BY added_at,evidence_id",
            (belief_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def add_world_belief_evidence(
        self, belief_id: str, evidence_id: str, run_id: str, stance: str, added_at: str
    ) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO world_belief_evidence(belief_id,evidence_id,run_id,stance,added_at) "
            "VALUES(?,?,?,?,?)",
            (belief_id, evidence_id, run_id, stance, added_at),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def update_source_reputation(self, source_id: str, source_family: str, verified: bool, contradicted: bool):
        row=self.conn.execute("SELECT * FROM source_reputation WHERE source_id=?",(source_id,)).fetchone()
        obs=(row["observations"] if row else 0)+1
        vh=(row["verified_hits"] if row else 0)+(1 if verified else 0)
        ch=(row["contradiction_hits"] if row else 0)+(1 if contradicted else 0)
        score=max(0.0,min(1.0,(1+vh)/(2+obs+ch)))
        self.conn.execute("""
        INSERT INTO source_reputation VALUES(?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
          source_family=excluded.source_family,observations=excluded.observations,
          verified_hits=excluded.verified_hits,contradiction_hits=excluded.contradiction_hits,
          reliability_score=excluded.reliability_score
        """,(source_id,source_family,obs,vh,ch,score))
        self.conn.commit()
        return score

    def update_agent_performance(self, agent_id: str, accepted_delta=0, rejected_delta=0,
                                 verifier_pass_delta=0, count_run=False):
        row=self.conn.execute("SELECT * FROM agent_performance WHERE agent_id=?",(agent_id,)).fetchone()
        runs=(row["runs"] if row else 0)+(1 if count_run else 0)
        acc=(row["accepted_evidence"] if row else 0)+accepted_delta
        rej=(row["rejected_evidence"] if row else 0)+rejected_delta
        vp=(row["verifier_passes"] if row else 0)+verifier_pass_delta
        quality=(acc+1)/(acc+rej+2)
        verification=(vp+1)/(runs+2) if runs else 0.5
        score=max(0.0,min(1.0,0.7*quality+0.3*verification))
        self.conn.execute("""
        INSERT INTO agent_performance VALUES(?,?,?,?,?,?)
        ON CONFLICT(agent_id) DO UPDATE SET
          runs=excluded.runs,accepted_evidence=excluded.accepted_evidence,
          rejected_evidence=excluded.rejected_evidence,verifier_passes=excluded.verifier_passes,
          score=excluded.score
        """,(agent_id,runs,acc,rej,vp,score))
        self.conn.commit()
        return score

    def get_agent_performance(self, agent_id: str):
        return self.conn.execute("SELECT * FROM agent_performance WHERE agent_id=?",(agent_id,)).fetchone()

    def put_memory(self, m: MemoryRecord):
        if not m.embedding:
            raise ValueError("embedding cannot be empty")
        self.conn.execute("""
        INSERT INTO semantic_memory VALUES(?,?,?,?,?)
        ON CONFLICT(memory_id) DO UPDATE SET
          namespace=excluded.namespace,text=excluded.text,
          metadata_json=excluded.metadata_json,embedding_json=excluded.embedding_json
        """,(m.memory_id,m.namespace,m.text,json.dumps(m.metadata,sort_keys=True),json.dumps(list(m.embedding))))
        self.conn.commit()

    def list_memory(self, namespace: str | None = None):
        if namespace is None:
            rows=self.conn.execute("SELECT * FROM semantic_memory ORDER BY memory_id").fetchall()
        else:
            rows=self.conn.execute("SELECT * FROM semantic_memory WHERE namespace=? ORDER BY memory_id",(namespace,)).fetchall()
        return tuple(MemoryRecord(r["memory_id"],r["namespace"],r["text"],json.loads(r["metadata_json"]),
                                  tuple(float(x) for x in json.loads(r["embedding_json"]))) for r in rows)

def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a)!=len(b): raise ValueError("embedding dimensions must match")
    if not a: raise ValueError("embeddings cannot be empty")
    dot=sum(x*y for x,y in zip(a,b))
    na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return 0.0 if na==0 or nb==0 else dot/(na*nb)

class SemanticMemory:
    def __init__(self, store: SQLiteStateStore):
        self.store=store
    def remember(self, memory_id, namespace, text, embedding, metadata=None):
        self.store.put_memory(MemoryRecord(memory_id,namespace,text,dict(metadata or {}),
                                           tuple(float(x) for x in embedding)))
    def search(self, query_embedding, namespace=None, top_k=5, min_similarity=-1.0):
        if top_k<1: raise ValueError("top_k must be >=1")
        hits=[]
        for m in self.store.list_memory(namespace):
            sim=cosine_similarity(query_embedding,m.embedding)
            if sim>=min_similarity: hits.append(MemoryHit(m,sim))
        hits.sort(key=lambda h:h.similarity,reverse=True)
        return tuple(hits[:top_k])
