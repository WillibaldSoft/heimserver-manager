-- Add resumable phases, recheck selections, structured reasons and approval snapshots.
-- Idempotent; preserves original results. Rollback: stop Fotolabor jobs, restore
-- previous code and drop these two tables. No image files are changed.
CREATE TABLE IF NOT EXISTS fotolabor_job_details (
 job_id INTEGER PRIMARY KEY, phase TEXT NOT NULL DEFAULT 'inventory',
 inventory_done INTEGER NOT NULL DEFAULT 0, source_job INTEGER,
 selection TEXT NOT NULL DEFAULT '{}', consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fotolabor_file_details (
 job_id INTEGER NOT NULL, path TEXT NOT NULL, reason_code TEXT NOT NULL DEFAULT '',
 preview_bytes INTEGER NOT NULL DEFAULT 0, preview_xmp INTEGER NOT NULL DEFAULT 0,
 fingerprint TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id,path)
);
CREATE INDEX IF NOT EXISTS fotolabor_reason_filter ON fotolabor_file_details(job_id,reason_code,path);
CREATE INDEX IF NOT EXISTS fotolabor_pending_files ON fotolabor_files(job_id,status,path);
INSERT OR IGNORE INTO fotolabor_job_details(job_id,phase,inventory_done)
 SELECT id, CASE WHEN checked>0 THEN 'checking' ELSE 'inventory' END,
 CASE WHEN checked>0 OR state='completed' THEN 1 ELSE 0 END FROM fotolabor_jobs;
INSERT OR IGNORE INTO fotolabor_file_details(job_id,path,reason_code)
 SELECT job_id,path,CASE
 WHEN status='damaged' THEN 'damaged'
 WHEN status!='uncheckable' THEN ''
 WHEN reason LIKE '%Symlink%' THEN 'symlink'
 WHEN reason LIKE '%fehlt (Debian-Paket:%' THEN 'missing_decoder'
 WHEN reason LIKE '%kein vollständiger Decoder%' THEN 'unsupported_format'
 WHEN reason LIKE '%Zeitlimit%' THEN 'timeout'
 WHEN reason LIKE '%Permission denied%' OR reason LIKE '%No such file%' THEN 'access'
 WHEN reason LIKE '%verändert%' THEN 'changed'
 WHEN reason LIKE '%ExifTool%' THEN 'metadata_warning'
 WHEN reason LIKE '%LibRaw%' OR reason LIKE '%Warnung%' THEN 'decoder_warning'
 ELSE 'unknown' END FROM fotolabor_files;
