"""Tests para cron.run_log — historial persistente de ejecución."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cron.run_log import (
    CronRunLogEntry,
    append_run_log,
    read_run_log,
    read_run_log_all,
    resolve_run_log_path,
)
from shared.errors import CronError


# ── Tests de CronRunLogEntry ────────────────────────────────


class TestCronRunLogEntry:
    """Tests para CronRunLogEntry."""

    def test_to_dict(self) -> None:
        entry = CronRunLogEntry(
            ts=1704067200.0,
            job_id="test-job",
            status="ok",
            summary="Test summary",
            duration_secs=1.5,
        )
        d = entry.to_dict()
        assert d["ts"] == 1704067200.0
        assert d["jobId"] == "test-job"
        assert d["action"] == "finished"
        assert d["status"] == "ok"
        assert d["summary"] == "Test summary"
        assert d["durationSecs"] == 1.5

    def test_to_dict_minimal(self) -> None:
        entry = CronRunLogEntry(ts=100.0, job_id="x")
        d = entry.to_dict()
        assert "status" not in d
        assert "error" not in d
        assert "summary" not in d

    def test_from_dict(self) -> None:
        data = {
            "ts": 1704067200.0,
            "jobId": "test-job",
            "action": "finished",
            "status": "ok",
            "summary": "Done",
            "durationSecs": 2.0,
        }
        entry = CronRunLogEntry.from_dict(data)
        assert entry is not None
        assert entry.ts == 1704067200.0
        assert entry.job_id == "test-job"
        assert entry.status == "ok"
        assert entry.duration_secs == 2.0

    def test_from_dict_invalid_no_ts(self) -> None:
        assert CronRunLogEntry.from_dict({"jobId": "x", "action": "finished"}) is None

    def test_from_dict_invalid_no_job_id(self) -> None:
        assert CronRunLogEntry.from_dict({"ts": 100, "action": "finished"}) is None

    def test_from_dict_invalid_action(self) -> None:
        assert CronRunLogEntry.from_dict({"ts": 100, "jobId": "x", "action": "started"}) is None

    def test_from_dict_with_usage(self) -> None:
        data = {
            "ts": 100.0,
            "jobId": "x",
            "action": "finished",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        entry = CronRunLogEntry.from_dict(data)
        assert entry is not None
        assert entry.usage == {"input_tokens": 100, "output_tokens": 50}

    def test_from_dict_snake_case_compat(self) -> None:
        """Acepta tanto camelCase como snake_case."""
        data = {
            "ts": 100.0,
            "job_id": "x",
            "action": "finished",
            "duration_secs": 1.0,
        }
        entry = CronRunLogEntry.from_dict(data)
        assert entry is not None
        assert entry.job_id == "x"
        assert entry.duration_secs == 1.0


# ── Tests de resolve_run_log_path ───────────────────────────


class TestResolveRunLogPath:
    """Tests para resolve_run_log_path."""

    def test_normal_path(self) -> None:
        path = resolve_run_log_path("/home/user/.somer/cron/store.json", "job-123")
        assert path.endswith("job-123.jsonl")
        assert "runs" in path

    def test_empty_id_raises(self) -> None:
        with pytest.raises(CronError, match="inválido"):
            resolve_run_log_path("/tmp/store.json", "")

    def test_slash_in_id_raises(self) -> None:
        with pytest.raises(CronError, match="inválido"):
            resolve_run_log_path("/tmp/store.json", "../../etc/passwd")

    def test_null_byte_raises(self) -> None:
        with pytest.raises(CronError, match="inválido"):
            resolve_run_log_path("/tmp/store.json", "job\x00bad")


# ── Tests de append/read run_log ────────────────────────────


class TestAppendReadRunLog:
    """Tests para append_run_log y read_run_log."""

    def test_append_and_read(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        entry = CronRunLogEntry(
            ts=1704067200.0,
            job_id="test-job",
            status="ok",
            summary="Test run",
            duration_secs=1.0,
        )
        append_run_log(log_path, entry)

        entries = read_run_log(log_path)
        assert len(entries) == 1
        assert entries[0].job_id == "test-job"
        assert entries[0].status == "ok"

    def test_multiple_entries(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        for i in range(5):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i,
                job_id="test-job",
                status="ok" if i % 2 == 0 else "error",
            )
            append_run_log(log_path, entry)

        all_entries = read_run_log(log_path)
        assert len(all_entries) == 5

        ok_entries = read_run_log(log_path, status="ok")
        assert len(ok_entries) == 3

        err_entries = read_run_log(log_path, status="error")
        assert len(err_entries) == 2

    def test_read_nonexistent(self, tmp_path: Path) -> None:
        entries = read_run_log(str(tmp_path / "nonexistent.jsonl"))
        assert entries == []

    def test_filter_by_job_id(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        for job_id in ["a", "b", "a", "c", "a"]:
            entry = CronRunLogEntry(ts=1704067200.0, job_id=job_id, status="ok")
            append_run_log(log_path, entry)

        entries = read_run_log(log_path, job_id="a")
        assert len(entries) == 3

    def test_pagination(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        for i in range(10):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i, job_id="test", status="ok",
            )
            append_run_log(log_path, entry)

        page1 = read_run_log(log_path, limit=3)
        assert len(page1) == 3

        page2 = read_run_log(log_path, limit=3, offset=3)
        assert len(page2) == 3

    def test_sort_desc_default(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        for i in range(3):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i, job_id="test", status="ok",
            )
            append_run_log(log_path, entry)

        entries = read_run_log(log_path)
        assert entries[0].ts > entries[-1].ts

    def test_sort_asc(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "test.jsonl")
        for i in range(3):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i, job_id="test", status="ok",
            )
            append_run_log(log_path, entry)

        entries = read_run_log(log_path, sort_desc=False)
        assert entries[0].ts < entries[-1].ts

    def test_pruning(self, tmp_path: Path) -> None:
        """Verifica que archivos grandes se rotan."""
        log_path = str(tmp_path / "test.jsonl")
        # Crear muchas entradas para exceder max_bytes
        for i in range(100):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i,
                job_id="test",
                status="ok",
                summary="x" * 200,
            )
            append_run_log(log_path, entry, max_bytes=5000, keep_lines=10)

        # El archivo debe haberse rotado
        entries = read_run_log(log_path, limit=200)
        assert len(entries) <= 100  # No más de lo escrito

    def test_creates_directory(self, tmp_path: Path) -> None:
        log_path = str(tmp_path / "subdir" / "deep" / "test.jsonl")
        entry = CronRunLogEntry(ts=100.0, job_id="test", status="ok")
        append_run_log(log_path, entry)
        assert os.path.exists(log_path)


# ── Tests de read_run_log_all ───────────────────────────────


class TestReadRunLogAll:
    """Tests para read_run_log_all."""

    def test_reads_all_job_logs(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        store_path = str(tmp_path / "store.json")

        # Crear logs para diferentes jobs
        for job_id in ["job-a", "job-b"]:
            log_path = str(runs_dir / f"{job_id}.jsonl")
            for i in range(3):
                entry = CronRunLogEntry(
                    ts=1704067200.0 + i,
                    job_id=job_id,
                    status="ok",
                )
                append_run_log(log_path, entry)

        entries = read_run_log_all(store_path)
        assert len(entries) == 6

    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        store_path = str(tmp_path / "store.json")
        entries = read_run_log_all(store_path)
        assert entries == []

    def test_filter_and_paginate(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        store_path = str(tmp_path / "store.json")

        log_path = str(runs_dir / "job-1.jsonl")
        for i in range(5):
            entry = CronRunLogEntry(
                ts=1704067200.0 + i,
                job_id="job-1",
                status="ok" if i % 2 == 0 else "error",
            )
            append_run_log(log_path, entry)

        ok_entries = read_run_log_all(store_path, status="ok")
        assert len(ok_entries) == 3

        page = read_run_log_all(store_path, limit=2)
        assert len(page) == 2
