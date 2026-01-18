"""Tests for backup module functionality."""

import json
from pathlib import Path

import pytest

from linto.backup import DATABASE_CONFIGS, BackupResult, write_manifest


class TestBackupResult:
    """Test BackupResult dataclass."""

    def test_backup_result_success(self):
        """BackupResult correctly stores success state."""
        result = BackupResult(
            name="studio-mongodb",
            db_type="mongodb",
            file="studio-mongodb.gz",
            size_bytes=1024,
            status="success",
        )
        assert result.status == "success"
        assert result.error is None
        assert result.name == "studio-mongodb"
        assert result.db_type == "mongodb"
        assert result.file == "studio-mongodb.gz"
        assert result.size_bytes == 1024

    def test_backup_result_failure(self):
        """BackupResult correctly stores failure state."""
        result = BackupResult(
            name="studio-mongodb",
            db_type="mongodb",
            file="",
            size_bytes=0,
            status="failed",
            error="Connection refused",
        )
        assert result.status == "failed"
        assert result.error == "Connection refused"
        assert result.size_bytes == 0

    def test_backup_result_postgres_type(self):
        """BackupResult handles postgres db_type."""
        result = BackupResult(
            name="live-postgres",
            db_type="postgres",
            file="live-postgres.sql.gz",
            size_bytes=2048,
            status="success",
        )
        assert result.db_type == "postgres"
        assert result.status == "success"


class TestDatabaseConfigs:
    """Test DATABASE_CONFIGS structure."""

    def test_database_configs_structure(self):
        """DATABASE_CONFIGS has required fields."""
        assert len(DATABASE_CONFIGS) > 0

        for config in DATABASE_CONFIGS:
            assert "name" in config
            assert "type" in config
            assert config["type"] in ("mongodb", "postgres")
            assert "label" in config

    def test_database_configs_contains_expected_databases(self):
        """DATABASE_CONFIGS includes expected database services."""
        names = [c["name"] for c in DATABASE_CONFIGS]
        assert "studio-mongodb" in names
        assert "stt-mongodb" in names
        assert "live-postgres" in names
        assert "llm-postgres" in names

    def test_database_configs_labels_format(self):
        """DATABASE_CONFIGS labels follow Kubernetes convention."""
        for config in DATABASE_CONFIGS:
            label = config["label"]
            assert "=" in label
            assert label.startswith("app.kubernetes.io/name=")


class TestWriteManifest:
    """Test manifest generation."""

    def test_write_manifest(self, tmp_path):
        """Manifest is written with correct structure."""
        results = [
            BackupResult("studio-mongodb", "mongodb", str(tmp_path / "studio-mongodb.gz"), 1024, "success"),
            BackupResult("live-postgres", "postgres", "", 0, "failed", "Pod not found"),
        ]

        write_manifest(tmp_path, "test-profile", results)

        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["profile"] == "test-profile"
        assert "timestamp" in manifest
        assert len(manifest["databases"]) == 2
        assert manifest["databases"][0]["status"] == "success"
        assert manifest["databases"][1]["error"] == "Pod not found"

    def test_write_manifest_timestamp_format(self, tmp_path):
        """Manifest timestamp is in ISO8601 format."""
        results = [
            BackupResult("studio-mongodb", "mongodb", "studio-mongodb.gz", 1024, "success"),
        ]

        write_manifest(tmp_path, "test-profile", results)

        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        # Check timestamp is valid ISO8601 with timezone
        timestamp = manifest["timestamp"]
        from datetime import datetime

        # Should parse without error
        datetime.fromisoformat(timestamp)
        # Should contain timezone info (ends with +00:00 or Z)
        assert "+" in timestamp or "Z" in timestamp

    def test_write_manifest_database_fields(self, tmp_path):
        """Manifest database entries have all required fields."""
        results = [
            BackupResult("studio-mongodb", "mongodb", str(tmp_path / "studio-mongodb.gz"), 1024, "success"),
        ]

        write_manifest(tmp_path, "test-profile", results)

        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        db_entry = manifest["databases"][0]
        assert "name" in db_entry
        assert "type" in db_entry
        assert "file" in db_entry
        assert "size_bytes" in db_entry
        assert "status" in db_entry
        assert "error" in db_entry

    def test_write_manifest_empty_results(self, tmp_path):
        """Manifest handles empty results list."""
        results = []

        write_manifest(tmp_path, "empty-profile", results)

        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["profile"] == "empty-profile"
        assert manifest["databases"] == []
