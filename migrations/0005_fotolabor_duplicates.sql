CREATE TABLE fotolabor_hashes (
 job_id INTEGER NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL,
 bytes INTEGER NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL,
 PRIMARY KEY(job_id,path)
);
CREATE INDEX fotolabor_hash_groups ON fotolabor_hashes(job_id,digest,bytes);
CREATE INDEX fotolabor_size_groups ON fotolabor_files(job_id,bytes);
