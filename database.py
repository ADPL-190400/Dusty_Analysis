"""
database.py - SQLite persistence layer for Dust Inspection results.
Handles history logging and retrieval.
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


DB_PATH = Path("data/inspection_history.db")
IMAGE_DIR = Path("data/captures")


@dataclass
class InspectionRecord:
    id: Optional[int]
    timestamp: str
    density_score: float
    pixel_count: int
    status: str
    image_path: str
    roi_width: int
    roi_height: int


def init_db() -> None:
    """Initialize database schema on first run."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inspections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            density_pct REAL    NOT NULL,
            pixel_count INTEGER NOT NULL,
            status      TEXT    NOT NULL,
            image_path  TEXT,
            roi_width   INTEGER,
            roi_height  INTEGER
        )
    """)
    conn.commit()
    conn.close()


def save_inspection(record: InspectionRecord) -> int:
    """
    Persist one inspection result. Returns the new row ID.

    Pattern:
        1. Save annotated frame to disk (caller passes image_path already written).
        2. INSERT metadata row → get ROWID.
        3. Return ID so UI can confirm the save.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO inspections
           (timestamp, density_pct, pixel_count, status, image_path, roi_width, roi_height)
           VALUES (?,?,?,?,?,?,?)""",
        (
            record.timestamp,
            record.density_score,
            record.pixel_count,
            record.status,
            record.image_path,
            record.roi_width,
            record.roi_height,
        ),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def fetch_history(limit: int = 100) -> list[InspectionRecord]:
    """Return the most recent `limit` inspection records, newest first."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM inspections ORDER BY id DESC LIMIT ?""", (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [
        InspectionRecord(
            id=r["id"],
            timestamp=r["timestamp"],
            density_score=r["density_pct"],
            pixel_count=r["pixel_count"],
            status=r["status"],
            image_path=r["image_path"],
            roi_width=r["roi_width"],
            roi_height=r["roi_height"],
        )
        for r in rows
    ]


def delete_record(record_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM inspections WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
