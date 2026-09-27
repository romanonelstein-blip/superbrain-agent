CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS nexus_runs(
  run_id TEXT PRIMARY KEY,status TEXT NOT NULL,question TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),final_value TEXT
);
CREATE TABLE IF NOT EXISTS nexus_semantic_memory(
  memory_id TEXT PRIMARY KEY,namespace TEXT NOT NULL,text TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding vector(1536) NOT NULL
);
CREATE INDEX IF NOT EXISTS nexus_semantic_memory_embedding_hnsw
  ON nexus_semantic_memory USING hnsw (embedding vector_cosine_ops);
