CREATE TABLE fotolabor_archive (
 path TEXT PRIMARY KEY, first_digest TEXT NOT NULL, latest_digest TEXT NOT NULL,
 signature TEXT NOT NULL, result TEXT NOT NULL, checked_job INTEGER NOT NULL,
 updated TEXT NOT NULL
);
CREATE TABLE fotolabor_observations (
 job_id INTEGER NOT NULL,path TEXT NOT NULL,digest TEXT NOT NULL,
 change TEXT NOT NULL,reused INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(job_id,path)
);
CREATE INDEX fotolabor_observation_changes ON fotolabor_observations(job_id,change);
CREATE TABLE fotolabor_schedules (
 id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,
 mode TEXT NOT NULL,clock TEXT NOT NULL,days TEXT NOT NULL,options TEXT NOT NULL,
 next_at INTEGER NOT NULL,last_job INTEGER,last_error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE fotolabor_restores (
 job_id INTEGER PRIMARY KEY,path TEXT NOT NULL,status TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '',tiff TEXT NOT NULL DEFAULT '',jpeg TEXT NOT NULL DEFAULT ''
);
