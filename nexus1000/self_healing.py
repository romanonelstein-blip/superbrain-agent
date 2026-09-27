from __future__ import annotations
import json, shutil, time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from .persistence import SQLiteStateStore

def _utc_now(): return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class HealingPolicy:
    stale_scheduler_seconds:int=3600
    failure_quarantine_threshold:int=5
    quarantine_seconds:int=1800
    backup_keep:int=5

@dataclass(frozen=True)
class HealingEvent:
    component:str; condition:str; action:str; outcome:str; detail:str; created_at:str

class SelfHealingController:
    """Bounded recovery: detect, diagnose, recover, verify, log, escalate."""
    def __init__(self,database_path,*,backup_dir=None,policy=None,clock=time.time):
        self.database_path=Path(database_path)
        self.backup_dir=Path(backup_dir) if backup_dir else self.database_path.parent/"backups"
        self.policy=policy or HealingPolicy(); self.clock=clock
        self.backup_dir.mkdir(parents=True,exist_ok=True)
        self.event_log=self.database_path.parent/"self-healing-events.jsonl"
    def _emit(self,c,cond,a,out,detail):
        e=HealingEvent(c,cond,a,out,detail,_utc_now())
        with self.event_log.open("a",encoding="utf-8") as f:f.write(json.dumps(asdict(e),sort_keys=True)+"\n")
        return e
    def _verified_backups(self):
        out=[]
        for p in sorted(self.backup_dir.glob("superbrain-*.sqlite3"),key=lambda x:x.stat().st_mtime,reverse=True):
            try:
                with SQLiteStateStore(p) as s: ok,_=s.integrity_check()
                if ok:out.append(p)
            except Exception:pass
        return out
    def create_verified_backup(self):
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target=self.backup_dir/f"superbrain-{stamp}.sqlite3"
        with SQLiteStateStore(self.database_path) as s:s.backup_to(target)
        for old in self._verified_backups()[self.policy.backup_keep:]:old.unlink(missing_ok=True)
        return self._emit("database","scheduled_backup","create_verified_backup","HEALED",str(target))
    def heal_database(self):
        try:
            with SQLiteStateStore(self.database_path) as s:ok,detail=s.integrity_check()
        except Exception as exc:ok,detail=False,f"{type(exc).__name__}: {exc}"
        if ok:return self._emit("database","integrity","none","HEALTHY",detail)
        backups=self._verified_backups()
        if not backups:return self._emit("database","integrity","restore_latest_backup","ESCALATE",f"{detail}; no verified backup")
        chosen=backups[0]
        if self.database_path.exists():shutil.copy2(self.database_path,self.database_path.with_suffix(self.database_path.suffix+".corrupt"))
        try:
            tmp=self.database_path.with_suffix(self.database_path.suffix+".restore");shutil.copy2(chosen,tmp);tmp.replace(self.database_path)
            with SQLiteStateStore(self.database_path) as s:ok2,detail2=s.integrity_check()
            if not ok2:raise RuntimeError(detail2)
        except Exception as exc:return self._emit("database","integrity","restore_latest_backup","ESCALATE",f"{type(exc).__name__}: {exc}")
        return self._emit("database","integrity","restore_latest_backup","HEALED",f"restored {chosen.name}")
    def heal_scheduler(self,job_name="continuous-intelligence"):
        now=float(self.clock())
        with SQLiteStateStore(self.database_path) as store:
            state=store.get_scheduler_job(job_name)
            if state is None:return self._emit("scheduler","missing_job","none","ESCALATE",job_name)
            failures=int(state.get("consecutive_failures",0))
            if failures>=self.policy.failure_quarantine_threshold:
                state["enabled"]=False;state["next_run_at"]=now+self.policy.quarantine_seconds
                state["last_error"]=(state.get("last_error") or "")+" | self-healing quarantine";state["updated_at"]=_utc_now();store.put_scheduler_job(state)
                return self._emit("scheduler","failure_storm","quarantine","HEALED",f"{failures} consecutive failures")
            due=float(state["next_run_at"])
            if state["enabled"] and due<now-self.policy.stale_scheduler_seconds:
                state["next_run_at"]=now;state["updated_at"]=_utc_now();store.put_scheduler_job(state)
                return self._emit("scheduler","stale_due_time","reschedule_now","HEALED",f"old next_run_at={due}")
        return self._emit("scheduler","state","none","HEALTHY",job_name)
    def run_health_cycle(self,job_name="continuous-intelligence",*,make_backup=True):
        events=[self.heal_database()]
        if events[-1].outcome=="ESCALATE":return {"status":"ESCALATE","events":[asdict(e) for e in events]}
        events.append(self.heal_scheduler(job_name))
        if make_backup:events.append(self.create_verified_backup())
        status="ESCALATE" if any(e.outcome=="ESCALATE" for e in events) else ("HEALED" if any(e.outcome=="HEALED" and e.action!="create_verified_backup" for e in events) else "HEALTHY")
        return {"status":status,"events":[asdict(e) for e in events]}
