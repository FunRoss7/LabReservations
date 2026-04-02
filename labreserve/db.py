import sqlite3
import contextlib
from datetime import datetime

from labreserve.config import DB_PATH


def init_db():
    with _connect() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS reservations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                machine      TEXT NOT NULL,
                reserved_by  TEXT NOT NULL,
                reserved_at  TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                released_at  TEXT,
                status       TEXT NOT NULL DEFAULT 'active'
            )
        ''')


@contextlib.contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_reservation(machine, reserved_by, expires_at):
    with _connect() as conn:
        conn.execute(
            'INSERT INTO reservations (machine, reserved_by, reserved_at, expires_at) VALUES (?, ?, ?, ?)',
            (machine, reserved_by, datetime.now().isoformat(timespec='seconds'), expires_at.isoformat(timespec='seconds'))
        )


def get_active_reservation(machine):
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM reservations WHERE machine = ? AND status = "active" ORDER BY reserved_at DESC LIMIT 1',
            (machine,)
        ).fetchone()
        return dict(row) if row else None


def record_release(machine):
    with _connect() as conn:
        conn.execute(
            'UPDATE reservations SET status = "released", released_at = ? WHERE machine = ? AND status = "active"',
            (datetime.now().isoformat(timespec='seconds'), machine)
        )


def list_reservations(active_only=False):
    with _connect() as conn:
        if active_only:
            rows = conn.execute(
                'SELECT * FROM reservations WHERE status = "active" ORDER BY expires_at'
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM reservations ORDER BY reserved_at DESC'
            ).fetchall()
        return [dict(r) for r in rows]
