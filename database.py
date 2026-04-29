import sqlite3
import logging
from datetime import datetime
from contextlib import contextmanager

class Database:
    def __init__(self, db_path="nmap_traces.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connection(self):
        """Context manager for thread-safe SQLite connections with WAL mode."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initializes schema and handles migrations."""
        with self.connection() as conn:
            cursor = conn.cursor()
            # Core Tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL UNIQUE,
                    port INTEGER DEFAULT 443
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server TEXT NOT NULL,
                    port INTEGER,
                    timestamp DATETIME,
                    status TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id INTEGER,
                    hop_index INTEGER,
                    rtt REAL,
                    address TEXT,
                    FOREIGN KEY (trace_id) REFERENCES traces (id)
                )
            """)
            
            # Migration: Ensure 'port' exists in traces
            cursor.execute("PRAGMA table_info(traces)")
            if 'port' not in [column[1] for column in cursor.fetchall()]:
                cursor.execute("ALTER TABLE traces ADD COLUMN port INTEGER")
            
            conn.commit()

    def add_server(self, address, port=443):
        try:
            with self.connection() as conn:
                conn.execute("INSERT INTO servers (address, port) VALUES (?, ?)", (address, port))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def remove_server(self, address):
        with self.connection() as conn:
            conn.execute("DELETE FROM servers WHERE address = ?", (address,))
            conn.commit()

    def get_servers(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT address, port FROM servers")
            return [{"server": r[0], "port": r[1]} for r in cursor.fetchall()]

    def add_trace(self, server, port, status, hops):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO traces (server, port, status, timestamp) VALUES (?, ?, ?, ?)",
                (server, port, status, timestamp)
            )
            trace_id = cursor.lastrowid
            for h in hops:
                cursor.execute(
                    "INSERT INTO hops (trace_id, hop_index, rtt, address) VALUES (?, ?, ?, ?)",
                    (trace_id, h['index'], h['rtt'], h['address'])
                )
            conn.commit()
            return trace_id

    def get_latency_data(self, server, limit=300):
        """Fetches last-hop latency for graphing."""
        with self.connection() as conn:
            query = """
                SELECT t.id, t.timestamp, h1.rtt as last_rtt, t.status
                FROM traces t
                JOIN (SELECT trace_id, MAX(hop_index) as max_idx FROM hops GROUP BY trace_id) h2
                  ON t.id = h2.trace_id
                JOIN hops h1 ON t.id = h1.trace_id AND h1.hop_index = h2.max_idx
                WHERE t.server = ?
                ORDER BY t.timestamp DESC LIMIT ?
            """
            cursor = conn.cursor()
            cursor.execute(query, (server, limit))
            return cursor.fetchall()

    def get_hops(self, trace_id):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT hop_index, rtt, address FROM hops WHERE trace_id = ? ORDER BY hop_index", (int(trace_id),))
            return cursor.fetchall()

    def clear_history(self):
        with self.connection() as conn:
            conn.execute("DELETE FROM hops")
            conn.execute("DELETE FROM traces")
            conn.commit()
