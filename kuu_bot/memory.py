import sqlite3
import os
import time
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")
DB_PATH = os.path.join(DATA_DIR, "memory.db")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma")

TTL_COOLING = 14 * 86400
TTL_FROZEN = 30 * 86400
TTL_TOMBSTONE = 90 * 86400

_chroma_collection = None
_chroma_enabled = False


def _init_chroma():
    global _chroma_collection, _chroma_enabled
    if _chroma_collection is not None:
        return
    try:
        import chromadb
        os.makedirs(CHROMA_PATH, exist_ok=True)
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _chroma_collection = client.get_or_create_collection(
            name="kuu_memories",
            metadata={"hnsw:space": "cosine"}
        )
        _chroma_enabled = True
    except Exception:
        _chroma_enabled = False


def _get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fragments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            tags TEXT DEFAULT '',
            confidence INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            last_accessed REAL,
            access_count INTEGER DEFAULT 0,
            source_session TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            entity_id INTEGER DEFAULT 0,
            consolidated INTEGER DEFAULT 0
        );
    """)
    # Migrate old table
    try:
        old = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'").fetchone()
        if old:
            conn.execute("""
                INSERT INTO fragments (content, tags, confidence, created_at, last_accessed, access_count, source_session)
                SELECT content, tags, confidence, created_at, last_accessed, access_count, source_session
                FROM memories WHERE status = 'active' AND id NOT IN (SELECT id FROM fragments)
            """)
            conn.execute("DROP TABLE IF EXISTS memories")
            conn.execute("DROP TABLE IF EXISTS memories_fts")
    except Exception:
        pass
    conn.executescript("""

        CREATE VIRTUAL TABLE IF NOT EXISTS fragments_fts
            USING fts5(content, tags, content='fragments', content_rowid='id');

        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT NOT NULL,
            content TEXT NOT NULL,
            fragment_ids TEXT DEFAULT '[]',
            tags TEXT DEFAULT '',
            confidence INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            last_accessed REAL,
            access_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            emotional_weight REAL DEFAULT 0.5
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
            USING fts5(content, tags, content='episodes', content_rowid='id');

        CREATE TABLE IF NOT EXISTS entity_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'other',
            overview TEXT DEFAULT '',
            fragment_count INTEGER DEFAULT 0,
            episode_count INTEGER DEFAULT 0,
            first_seen REAL,
            last_seen REAL,
            status TEXT DEFAULT 'active',
            tags TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fragment_entities (
            fragment_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            PRIMARY KEY(fragment_id, entity_id)
        );

        CREATE TABLE IF NOT EXISTS memory_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            confidence INTEGER DEFAULT 1,
            ttl_hours REAL DEFAULT 24,
            created_at REAL NOT NULL,
            expires_at REAL,
            status TEXT DEFAULT 'active'
        );
    """)
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS frag_fts_insert AFTER INSERT ON fragments BEGIN
            INSERT INTO fragments_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS frag_fts_delete AFTER DELETE ON fragments BEGIN
            INSERT INTO fragments_fts(fragments_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS frag_fts_update AFTER UPDATE ON fragments BEGIN
            INSERT INTO fragments_fts(fragments_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
            INSERT INTO fragments_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS epi_fts_insert AFTER INSERT ON episodes BEGIN
            INSERT INTO episodes_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS epi_fts_delete AFTER DELETE ON episodes BEGIN
            INSERT INTO episodes_fts(episodes_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS epi_fts_update AFTER UPDATE ON episodes BEGIN
            INSERT INTO episodes_fts(episodes_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
            INSERT INTO episodes_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END;
    """)
    conn.commit()
    conn.close()


# ─── Fragments ─────────────────────

def remember(content: str, tags: str = "", session_name: str = "") -> int:
    _init_db()
    conn = _get_db()
    now = time.time()

    existing = conn.execute(
        "SELECT id, confidence FROM fragments WHERE content = ?",
        (content.strip(),)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE fragments SET confidence = MIN(?, 5), access_count = access_count + 1, "
            "last_accessed = ?, tags = ? WHERE id = ?",
            (existing["confidence"] + 1, now, tags.strip(), existing["id"])
        )
        conn.commit()
        conn.close()
        return existing["id"]

    conn.execute(
        "INSERT INTO fragments (content, tags, confidence, created_at, source_session) "
        "VALUES (?, ?, ?, ?, ?)",
        (content.strip(), tags.strip(), 1, now, session_name)
    )
    frag_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    _index_chroma(frag_id, content.strip(), tags.strip())
    return 0


def _index_chroma(frag_id: int, content: str, tags: str):
    global _chroma_enabled
    _init_chroma()
    if not _chroma_enabled:
        return
    try:
        _chroma_collection.upsert(
            ids=[str(frag_id)],
            documents=[content],
            metadatas=[{"tags": tags, "status": "active"}]
        )
    except Exception:
        pass


def _search_chroma(query: str, limit: int = 10) -> list:
    global _chroma_enabled
    _init_chroma()
    if not _chroma_enabled:
        return []
    try:
        results = _chroma_collection.query(
            query_texts=[query],
            n_results=limit,
            where={"status": "active"}
        )
        ids = results.get("ids", [[]])[0]
        return ids
    except Exception:
        return []


def recall(query: str, limit: int = 10) -> list:
    _init_db()
    conn = _get_db()
    now = time.time()

    rows = []
    try:
        rows = conn.execute(
            "SELECT f.* FROM fragments f JOIN fragments_fts ft ON f.id = ft.rowid "
            "WHERE fragments_fts MATCH ? AND f.status = 'active' "
            "ORDER BY f.confidence DESC, f.created_at DESC LIMIT ?",
            (query, limit)
        ).fetchall()
    except Exception:
        pass

    fts_ids = {r["id"] for r in rows} if rows else set()

    chroma_ids = _search_chroma(query, limit * 2)
    vector_ids = [int(cid) for cid in chroma_ids if cid.isdigit() and int(cid) not in fts_ids]

    if vector_ids:
        placeholders = ",".join("?" * len(vector_ids))
        try:
            extra = conn.execute(
                f"SELECT * FROM fragments WHERE id IN ({placeholders}) AND status = 'active' "
                "ORDER BY confidence DESC, created_at DESC LIMIT ?",
                vector_ids + [limit]
            ).fetchall()
            rows = list(rows) + list(extra)
        except Exception:
            pass

    if not rows:
        rows = conn.execute(
            "SELECT * FROM fragments WHERE (content LIKE ? OR tags LIKE ?) AND status = 'active' "
            "ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        ).fetchall()

    for row in rows:
        conn.execute(
            "UPDATE fragments SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, row["id"])
        )
    conn.commit()
    conn.close()

    return [dict(r) for r in rows]


def get_recent_fragments(limit: int = 5) -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM fragments WHERE status = 'active' ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fragments_by_tag(tag: str, limit: int = 10) -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM fragments WHERE tags LIKE ? AND status = 'active' "
        "ORDER BY confidence DESC, created_at DESC LIMIT ?",
        (f"%{tag}%", limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_fragments() -> int:
    _init_db()
    conn = _get_db()
    row = conn.execute("SELECT COUNT(*) as c FROM fragments WHERE status = 'active'").fetchone()
    conn.close()
    return row["c"] if row else 0


def get_unconsolidated_fragments() -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM fragments WHERE consolidated = 0 AND status = 'active'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_consolidated(fragment_ids: list):
    _init_db()
    conn = _get_db()
    for fid in fragment_ids:
        conn.execute("UPDATE fragments SET consolidated = 1 WHERE id = ?", (fid,))
    conn.commit()
    conn.close()


# ─── Entities ─────────────────────

def get_or_create_entity(name: str, category: str = "other") -> dict:
    _init_db()
    conn = _get_db()
    now = time.time()
    row = conn.execute("SELECT * FROM entity_profiles WHERE name = ?", (name,)).fetchone()
    if row:
        conn.close()
        return dict(row)
    conn.execute(
        "INSERT INTO entity_profiles (name, category, first_seen, last_seen, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, category, now, now, now)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM entity_profiles WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def link_fragment_to_entity(fragment_id: int, entity_name: str):
    _init_db()
    conn = _get_db()
    entity = get_or_create_entity(entity_name)
    conn = _get_db()
    conn.execute(
        "INSERT OR IGNORE INTO fragment_entities (fragment_id, entity_id) VALUES (?, ?)",
        (fragment_id, entity["id"])
    )
    conn.execute(
        "UPDATE fragments SET entity_id = ? WHERE id = ?",
        (entity["id"], fragment_id)
    )
    conn.execute(
        "UPDATE entity_profiles SET fragment_count = fragment_count + 1, last_seen = ? WHERE id = ?",
        (time.time(), entity["id"])
    )
    conn.commit()
    conn.close()


def update_entity_overview(name: str, overview: str):
    _init_db()
    conn = _get_db()
    conn.execute(
        "UPDATE entity_profiles SET overview = ? WHERE name = ?",
        (overview, name)
    )
    conn.commit()
    conn.close()


def get_entity(name: str) -> dict | None:
    _init_db()
    conn = _get_db()
    row = conn.execute("SELECT * FROM entity_profiles WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_entities() -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM entity_profiles WHERE status = 'active' ORDER BY fragment_count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_entity_episodes(name: str, limit: int = 5) -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM episodes WHERE entity = ? AND status = 'active' "
        "ORDER BY created_at DESC LIMIT ?",
        (name, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Episodes ─────────────────────

def save_episode(entity: str, content: str, fragment_ids: list, tags: str = "", emotional_weight: float = 0.5):
    _init_db()
    conn = _get_db()
    conn.execute(
        "INSERT INTO episodes (entity, content, fragment_ids, tags, confidence, created_at, emotional_weight) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)",
        (entity, content, json.dumps(fragment_ids), tags, time.time(), emotional_weight)
    )
    conn.execute(
        "UPDATE entity_profiles SET episode_count = episode_count + 1 WHERE name = ?",
        (entity,)
    )
    conn.commit()
    conn.close()


def get_episodes_for_context(query: str, limit: int = 5) -> list:
    _init_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE episodes_fts MATCH ? AND status = 'active' "
            "ORDER BY confidence DESC LIMIT ?",
            (query, limit)
        ).fetchall()
    except Exception:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE (content LIKE ? OR entity LIKE ?) AND status = 'active' "
            "ORDER BY confidence DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        ).fetchall()
    now = time.time()
    for row in rows:
        conn.execute(
            "UPDATE episodes SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, row["id"])
        )
    conn.commit()
    conn.close()
    return [dict(r) for r in rows]


def get_all_episodes(limit: int = 10) -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM episodes WHERE status = 'active' ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── States ─────────────────────

def set_state(category: str, content: str, ttl_hours: float = 24):
    _init_db()
    conn = _get_db()
    now = time.time()
    conn.execute(
        "UPDATE memory_states SET status = 'resolved' WHERE category = ? AND status = 'active'",
        (category,)
    )
    conn.execute(
        "INSERT INTO memory_states (category, content, confidence, ttl_hours, created_at, expires_at) "
        "VALUES (?, ?, 1, ?, ?, ?)",
        (category, content, ttl_hours, now, now + ttl_hours * 3600)
    )
    conn.commit()
    conn.close()


def get_active_states() -> list:
    _init_db()
    conn = _get_db()
    now = time.time()
    conn.execute(
        "UPDATE memory_states SET status = 'expired' WHERE expires_at < ? AND status = 'active'",
        (now,)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM memory_states WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Tags ─────────────────────

def get_all_tags() -> list:
    _init_db()
    conn = _get_db()
    rows = conn.execute("SELECT tags FROM fragments WHERE status = 'active'").fetchall()
    conn.close()
    tags = set()
    for r in rows:
        for t in r["tags"].split(","):
            t = t.strip()
            if t:
                tags.add(t)
    return sorted(tags)


def group_fragments_by_tags(fragments: list) -> dict:
    groups = {}
    for f in fragments:
        for tag in f["tags"].split(","):
            tag = tag.strip()
            if not tag:
                continue
            if tag not in groups:
                groups[tag] = []
            groups[tag].append(f)
    return groups


# ─── TTL Lifecycle ────────────────

def run_lifecycle():
    _init_db()
    conn = _get_db()
    now = time.time()

    conn.execute(
        "UPDATE fragments SET status = 'cooling' "
        "WHERE status = 'active' AND (last_accessed IS NULL OR ? - last_accessed > ?)",
        (now, TTL_COOLING)
    )
    conn.execute(
        "UPDATE fragments SET status = 'frozen' "
        "WHERE status = 'cooling' AND (last_accessed IS NULL OR ? - last_accessed > ?)",
        (now, TTL_FROZEN)
    )
    conn.execute(
        "UPDATE fragments SET status = 'tombstone', content = '[expired]' "
        "WHERE status = 'frozen' AND (last_accessed IS NULL OR ? - last_accessed > ?)",
        (now, TTL_TOMBSTONE)
    )
    conn.execute(
        "UPDATE fragments SET status = 'active' "
        "WHERE status = 'cooling' AND last_accessed IS NOT NULL AND ? - last_accessed <= ?",
        (now, TTL_COOLING)
    )
    conn.commit()
    conn.close()


# ─── Context Injection ──────────

def recall_for_context(text: str, limit: int = 5) -> list:
    episodes = get_episodes_for_context(text, limit)
    if len(episodes) >= limit:
        return episodes
    fragments = recall(text, limit - len(episodes))
    existing_ids = {e["id"] for e in episodes}
    for f in fragments:
        fid = f.get("id")
        if fid and fid not in existing_ids:
            episodes.append({"id": f"f{fid}", "entity": "碎片", "content": f["content"], "confidence": f.get("confidence", 1), "type": "fragment"})
    return episodes


def count() -> int:
    return count_fragments()
