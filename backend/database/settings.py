"""SettingsDB - Database operations for user settings."""

import json
import sqlite3
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SettingsDB:
    """Database operations for user settings."""

    def __init__(self, db):
        self.db = db

    def _get_connection(self) -> sqlite3.Connection:
        return self.db._get_connection()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value (JSON parsed) or default."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row and row["value"]:
                try:
                    return json.loads(row["value"])
                except json.JSONDecodeError:
                    return row["value"]
            return default
        finally:
            conn.close()

    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value (will be JSON encoded)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            json_value = json.dumps(value) if not isinstance(value, str) else value
            cursor.execute("""
                INSERT INTO user_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, json_value))
            conn.commit()
        finally:
            conn.close()

    def delete_setting(self, key: str) -> bool:
        """Delete a setting. Returns True if deleted."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_settings WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings as a dictionary."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM user_settings")
            settings = {}
            for row in cursor.fetchall():
                try:
                    settings[row["key"]] = json.loads(row["value"])
                except json.JSONDecodeError:
                    settings[row["key"]] = row["value"]
            return settings
        finally:
            conn.close()
