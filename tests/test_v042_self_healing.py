import tempfile,unittest
from pathlib import Path
from nexus1000.persistence import SQLiteStateStore
from nexus1000.self_healing import HealingPolicy,SelfHealingController
class Clock:
 def __init__(self,v=10000.):self.v=v
 def __call__(self):return self.v
def job(db,**u):
 s={"job_name":"continuous-intelligence","enabled":True,"interval_seconds":30,"next_run_at":10000.,"last_run_at":None,"last_cycle_id":None,"consecutive_failures":0,"last_error":None,"updated_at":"now"};s.update(u)
 with SQLiteStateStore(db) as x:x.put_scheduler_job(s)
class T(unittest.TestCase):
 def test_stale(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/"s.db";job(db,next_run_at=1.);c=SelfHealingController(db,policy=HealingPolicy(stale_scheduler_seconds=60),clock=Clock());self.assertEqual(c.heal_scheduler().outcome,"HEALED")
 def test_quarantine(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/"s.db";job(db,consecutive_failures=5);c=SelfHealingController(db,clock=Clock());self.assertEqual(c.heal_scheduler().action,"quarantine")
 def test_restore(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/"s.db";job(db);c=SelfHealingController(db);c.create_verified_backup();db.write_bytes(b"broken");self.assertEqual(c.heal_database().outcome,"HEALED")
 def test_escalate(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/"s.db";db.write_bytes(b"broken");self.assertEqual(SelfHealingController(db).heal_database().outcome,"ESCALATE")
