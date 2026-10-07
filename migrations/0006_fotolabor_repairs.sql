CREATE TABLE fotolabor_repairs (
 job_id INTEGER NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL,
 reason TEXT NOT NULL, output TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(job_id,path)
);
CREATE INDEX fotolabor_repair_source ON fotolabor_repairs(path,status);
