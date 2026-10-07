CREATE TABLE fotolabor_applied (
 job_id INTEGER NOT NULL,path TEXT NOT NULL,repair_job INTEGER NOT NULL,
 output TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',backup TEXT NOT NULL DEFAULT '',
 source_digest TEXT NOT NULL DEFAULT '',applied_digest TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(job_id,path)
);
CREATE INDEX fotolabor_applied_paths ON fotolabor_applied(path,status,repair_job);
