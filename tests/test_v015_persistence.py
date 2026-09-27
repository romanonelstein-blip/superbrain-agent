import tempfile, unittest
from pathlib import Path
from nexus1000 import RunRecord,EvidenceRecord,SQLiteStateStore,SemanticMemory,cosine_similarity

class TestPersistence(unittest.TestCase):
    def test_run_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"n.db"; s=SQLiteStateStore(p)
            s.upsert_run(RunRecord("r","running","q","t1","t1")); s.close()
            with SQLiteStateStore(p) as s:
                self.assertEqual(s.get_run("r").status,"running")
    def test_evidence_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                s.upsert_run(RunRecord("r","running","q","t","t"))
                s.put_evidence(EvidenceRecord("e","r","c","support","s","f",.9,.8,.7,True))
                self.assertTrue(s.list_evidence("r")[0].verified)
    def test_evidence_upsert(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                s.upsert_run(RunRecord("r","running","q","t","t"))
                s.put_evidence(EvidenceRecord("e","r","one","support","s","f",.1,.1,.1,False))
                s.put_evidence(EvidenceRecord("e","r","two","support","s","f",.9,.9,.9,True))
                rows=s.list_evidence("r"); self.assertEqual(len(rows),1); self.assertEqual(rows[0].claim,"two")
    def test_source_reputation_changes(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                a=s.update_source_reputation("s","f",True,False)
                b=s.update_source_reputation("s","f",True,False)
                c=s.update_source_reputation("s","f",False,True)
                self.assertGreater(b,a); self.assertLess(c,b)
    def test_agent_performance_persists(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"n.db"; s=SQLiteStateStore(p)
            s.update_agent_performance("a",3,1,1,True); s.close()
            with SQLiteStateStore(p) as s:
                self.assertEqual(s.get_agent_performance("a")["accepted_evidence"],3)
    def test_cosine(self):
        self.assertAlmostEqual(cosine_similarity((1,0),(1,0)),1.0)
        self.assertAlmostEqual(cosine_similarity((1,0),(0,1)),0.0)
    def test_memory_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"n.db"; s=SQLiteStateStore(p); m=SemanticMemory(s)
            m.remember("m","sources","pattern",(1,0),{"risk":"high"}); s.close()
            with SQLiteStateStore(p) as s:
                self.assertEqual(s.list_memory("sources")[0].metadata["risk"],"high")
    def test_semantic_search(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                m=SemanticMemory(s)
                m.remember("a","n","close",(1,0)); m.remember("b","n","far",(0,1))
                hits=m.search((.9,.1),namespace="n",top_k=2)
                self.assertEqual(hits[0].memory.memory_id,"a")
    def test_namespace_filter(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                m=SemanticMemory(s)
                m.remember("a","x","x",(1,0)); m.remember("b","y","y",(1,0))
                self.assertEqual([h.memory.memory_id for h in m.search((1,0),namespace="x")],["a"])
    def test_top_k(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td)/"n.db") as s:
                m=SemanticMemory(s)
                for i in range(4): m.remember(str(i),"n",str(i),(1,float(i)))
                self.assertEqual(len(m.search((1,0),namespace="n",top_k=2)),2)
    def test_pgvector_schema_packaged(self):
        p=Path(__file__).resolve().parents[1]/"sql"/"postgres_pgvector_schema.sql"
        t=p.read_text(); self.assertIn("CREATE EXTENSION IF NOT EXISTS vector",t); self.assertIn("USING hnsw",t)

if __name__=="__main__":
    unittest.main()
