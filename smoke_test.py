"""Smoke test for pattern_store.py — run with: python smoke_test.py"""
import pathlib
import sys
import os

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from pattern_store import SQLiteBackend
import uuid

DB_PATH = pathlib.Path(f"data/test_smoke_{uuid.uuid4().hex[:8]}.db")

def main():
    db = SQLiteBackend(DB_PATH)

    # 1. save_checkpoint
    cid = db.save_checkpoint(
        summary="Testing the storage layer.",
        task_type="debugging",
        confidence=0.9,
        next_likely_step="Add more assertions.",
        elapsed_seconds=120.0,
    )
    print(f"[1] save_checkpoint OK -> id={cid[:8]}...")

    # 2. get_latest_checkpoint
    cp = db.get_latest_checkpoint()
    assert cp is not None
    assert cp["task_type"] == "debugging", f"Expected 'debugging', got {cp['task_type']}"
    print(f"[2] get_latest_checkpoint OK -> task_type={cp['task_type']}")

    # 3. get_checkpoint_by_id
    cp2 = db.get_checkpoint_by_id(cid)
    assert cp2 is not None
    assert cp2["id"] == cid
    print("[3] get_checkpoint_by_id OK")

    # 4. update_interval
    db.update_interval("debugging", 120.0)
    db.update_interval("debugging", 60.0)
    print("[4] update_interval OK")

    # 5. get_stats
    stats = db.get_stats()
    assert "debugging" in stats
    assert stats["debugging"]["count"] == 2
    avg = stats["debugging"]["avg_time_before_interrupt"]
    assert avg == 90.0, f"Expected avg=90.0, got {avg}"
    print(f"[5] get_stats OK -> count={stats['debugging']['count']}, avg={avg}s")

    # 6. save_feedback + get_recent_feedback
    db.save_feedback(cid, "new-feature")
    fb = db.get_recent_feedback()
    assert len(fb) == 1
    assert fb[0]["corrected_type"] == "new-feature"
    print("[6] save_feedback + get_recent_feedback OK")

    print()
    print("ALL pattern_store tests PASSED [OK]")

if __name__ == "__main__":
    try:
        main()
    finally:
        # Close WAL shm/wal sidecar files before cleanup
        import sqlite3
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass
        for suffix in ["", "-wal", "-shm"]:
            p = pathlib.Path(str(DB_PATH) + suffix)
            if p.exists():
                try:
                    os.unlink(p)
                except Exception:
                    pass
