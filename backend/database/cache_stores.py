"""SQLite-backed cache stores for various data types.

Contains: LifecycleCacheDB, WorkflowCacheDB, ContributorTimeSeriesCacheDB, CodeActivityCacheDB
"""

import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class LifecycleCacheDB:
    """Cache for PR lifecycle/review timing data in SQLite."""

    def __init__(self, db):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM pr_lifecycle_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "data": json.loads(row["data"]),
                    "updated_at": row["updated_at"]
                }
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO pr_lifecycle_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_hours: int = 2) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM pr_lifecycle_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            return age_hours > ttl_hours
        finally:
            conn.close()


class WorkflowCacheDB:
    """Cache for workflow runs data in SQLite."""

    def __init__(self, db):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM workflow_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "updated_at": row["updated_at"]
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Corrupt workflow cache for {repo}, treating as miss")
                    return None
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO workflow_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_minutes: int = 60) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM workflow_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_minutes = (datetime.now() - updated).total_seconds() / 60
            return age_minutes > ttl_minutes
        finally:
            conn.close()

    def get_all_repos(self) -> List[str]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT repo FROM workflow_cache")
            return [row["repo"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def clear(self) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM workflow_cache")
            conn.commit()
        finally:
            conn.close()


class ContributorTimeSeriesCacheDB:
    """Cache for per-contributor weekly time series data in SQLite."""

    def __init__(self, db):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM contributor_timeseries_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "updated_at": row["updated_at"]
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Corrupt contributor TS cache for {repo}, treating as miss")
                    return None
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO contributor_timeseries_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_hours: int = 24) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM contributor_timeseries_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            return age_hours > ttl_hours
        finally:
            conn.close()

    def clear(self) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM contributor_timeseries_cache")
            conn.commit()
        finally:
            conn.close()


class CodeActivityCacheDB:
    """Cache for code activity data in SQLite."""

    def __init__(self, db):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM code_activity_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "updated_at": row["updated_at"]
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Corrupt code activity cache for {repo}, treating as miss")
                    return None
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO code_activity_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_hours: int = 24) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM code_activity_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            return age_hours > ttl_hours
        finally:
            conn.close()

    def clear(self) -> None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM code_activity_cache")
            conn.commit()
        finally:
            conn.close()
