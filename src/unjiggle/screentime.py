"""Screen Time data reader. Gracefully degrades if unavailable.

Reads iPhone app usage from macOS knowledgeC.db (synced via iCloud).
Requires Full Disk Access on macOS 15+. Database may not exist on macOS 26+.
When unavailable, returns empty dict — callers fall back to heuristics.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_DB = Path.home() / "Library" / "Application Support" / "Knowledge" / "knowledgeC.db"
APPLE_EPOCH_OFFSET = 978307200


@dataclass
class AppUsage:
    bundle_id: str
    last_opened: datetime | None
    total_sessions: int
    avg_daily_opens: float
    total_minutes: float


def is_available() -> bool:
    """Check if Screen Time data is readable."""
    if not KNOWLEDGE_DB.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{KNOWLEDGE_DB}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM ZOBJECT LIMIT 1")
        conn.close()
        return True
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return False


def get_usage(bundle_ids: list[str] | None = None, iphone_only: bool = True) -> dict[str, AppUsage]:
    """Read per-app usage stats. Returns empty dict if unavailable."""
    if not is_available():
        return {}

    try:
        conn = sqlite3.connect(f"file:{KNOWLEDGE_DB}?mode=ro", uri=True)
        conn.execute("PRAGMA busy_timeout = 5000")

        device_filter = ""
        if iphone_only:
            device_filter = "AND ZSOURCE.ZDEVICEID IS NOT NULL"

        query = f"""
        SELECT
            ZOBJECT.ZVALUESTRING,
            MAX(ZOBJECT.ZSTARTDATE),
            COUNT(*),
            ROUND(COUNT(*) * 1.0 / MAX(1, JULIANDAY('NOW') -
                JULIANDAY(DATETIME(MIN(ZOBJECT.ZSTARTDATE) + {APPLE_EPOCH_OFFSET},
                'UNIXEPOCH'))), 1),
            ROUND(SUM(ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) / 60.0, 1)
        FROM ZOBJECT
            LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
        WHERE
            ZOBJECT.ZSTREAMNAME = '/app/usage'
            AND ZOBJECT.ZENDDATE > ZOBJECT.ZSTARTDATE
            {device_filter}
        GROUP BY ZOBJECT.ZVALUESTRING
        """

        results = {}
        for row in conn.execute(query):
            bid = row[0]
            if bundle_ids and bid not in bundle_ids:
                continue
            last_opened = None
            if row[1]:
                try:
                    last_opened = datetime.fromtimestamp(row[1] + APPLE_EPOCH_OFFSET, tz=timezone.utc)
                except (OSError, OverflowError):
                    pass
            results[bid] = AppUsage(
                bundle_id=bid,
                last_opened=last_opened,
                total_sessions=row[2] or 0,
                avg_daily_opens=row[3] or 0.0,
                total_minutes=row[4] or 0.0,
            )
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {}
