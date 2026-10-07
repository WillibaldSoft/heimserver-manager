-- Fotolabor jobs, per-file results and deletion audit. Idempotent.
-- Rollback: disable module/provider first; archive then drop fotolabor_* tables.
-- Does not alter any existing table or image file.
CREATE TABLE IF NOT EXISTS fotolabor_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT NOT NULL,
 state TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
 total INTEGER NOT NULL DEFAULT 0, checked INTEGER NOT NULL DEFAULT 0,
 bytes INTEGER NOT NULL DEFAULT 0, current TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', cancel INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fotolabor_files (
 job_id INTEGER NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
 bytes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
 reason TEXT NOT NULL DEFAULT '', category INTEGER, jpeg TEXT,
 safe INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(job_id,path)
);
CREATE INDEX IF NOT EXISTS fotolabor_result_filter ON fotolabor_files(job_id,status,category);
CREATE TABLE IF NOT EXISTS fotolabor_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
 path TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
