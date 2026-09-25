"""Durable idempotency and append-only outbox. Observer consumes, never serves inference."""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from decision_brain.edge_contracts import canonical

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS idempotency(scope TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,state TEXT NOT NULL,status INTEGER,response TEXT,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(seq INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT UNIQUE NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,event TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS traffic(seq INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,brain TEXT,version TEXT,status INTEGER,reason TEXT,seconds REAL);
            CREATE INDEX IF NOT EXISTS decisions_time ON decisions(created);
            CREATE INDEX IF NOT EXISTS traffic_time ON traffic(created,brain);
            CREATE TRIGGER IF NOT EXISTS no_update_decision BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'immutable decision'); END;
            CREATE TRIGGER IF NOT EXISTS no_delete_decision BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'immutable decision'); END;''')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def reserve(self,scope,fingerprint):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM idempotency WHERE scope=?',(scope,)).fetchone()
            if row:
                if row['fingerprint']!=fingerprint:return 'conflict',None
                if row['state']=='pending':return 'pending',None
                return 'replay',(row['status'],json.loads(row['response']))
            db.execute('INSERT INTO idempotency VALUES(?,?,?,NULL,NULL,?)',(scope,fingerprint,'pending',time.time()))
            return 'new',None
    def complete(self,scope,status,response,audit=None,event=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM idempotency WHERE scope=?',(scope,)).fetchone()
            if not row or row['state']!='pending':raise ValueError('invalid_idempotency_transition')
            if audit is not None:
                db.execute('INSERT INTO decisions(request_id,created,payload,event) VALUES(?,?,?,?)',(audit['request_id'],time.time(),canonical(audit),canonical(event)))
            db.execute('UPDATE idempotency SET state=?,status=?,response=? WHERE scope=?',('done',status,canonical(response),scope))
    def traffic(self,brain,version,status,reason,seconds):
        with self.connect() as db:db.execute('INSERT INTO traffic(created,brain,version,status,reason,seconds) VALUES(?,?,?,?,?,?)',(time.time(),brain,version,status,reason,seconds))
    def event(self,event_id):
        with self.connect() as db:row=db.execute('SELECT event FROM decisions WHERE request_id=?',(event_id,)).fetchone()
        if not row:raise KeyError(event_id)
        return json.loads(row[0])
