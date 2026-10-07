"""Keep relative file records, repairs and schedules tied to their image root."""
import copy
import hashlib
import sqlite3
from pathlib import Path
from server_settings import atomic, read


def context(ctx,root):
    marker=Path(ctx.state_dir)/'fotolabor-root.json'
    if not marker.exists():atomic(marker,{'original_root':str(root)})
    if read(marker).get('original_root')==str(root):return ctx
    # A different image collection must never reuse another collection's approvals.
    scoped=copy.copy(ctx)
    scoped.state_dir=Path(ctx.state_dir)/'fotolabor-collections'/hashlib.sha256(str(root).encode()).hexdigest()
    scoped.state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    scoped.db_path=scoped.state_dir/'fotolabor.sqlite3'
    def db():
        con=sqlite3.connect(str(scoped.db_path),timeout=30)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA busy_timeout=5000')
        return con
    scoped.db=db
    return scoped
