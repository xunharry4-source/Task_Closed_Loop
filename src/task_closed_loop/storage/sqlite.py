import sqlite3
SCHEMA="""
CREATE TABLE IF NOT EXISTS realities (reality_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (evidence_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, task_identity TEXT NOT NULL, reality_id TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_intents (execution_intent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (attempt_id TEXT PRIMARY KEY, execution_intent_id TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS effects (effect_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, execution_intent_id TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS diagnostic_runs (run_id TEXT PRIMARY KEY, root_class TEXT NOT NULL, payload_json TEXT NOT NULL);
"""
def initialize_database(path):
    con=sqlite3.connect(str(path)); con.executescript(SCHEMA); con.commit(); con.close()
