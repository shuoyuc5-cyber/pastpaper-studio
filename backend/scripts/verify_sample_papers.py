"""Run the Phase 1 acceptance check against the user's two real sample PDFs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = Path(os.environ.get('PASTPAPER_SAMPLE_DIR', PROJECT_ROOT / 'samples')).expanduser().resolve()
SAMPLE_QP = SAMPLE_ROOT / '0580_s26_qp_11.pdf'
SAMPLE_MS = SAMPLE_ROOT / '0580_s26_ms_11.pdf'


def main() -> None:
    for sample in (SAMPLE_QP, SAMPLE_MS):
        if not sample.is_file():
            raise SystemExit(f"Sample PDF not found: {sample}")

    with tempfile.TemporaryDirectory(prefix="pastpaper-phase1-") as temporary:
        root = Path(temporary)
        library = root / "library"
        library.mkdir()
        (library / SAMPLE_QP.name).symlink_to(SAMPLE_QP)
        (library / SAMPLE_MS.name).symlink_to(SAMPLE_MS)
        os.environ["PASTPAPER_DATA_DIR"] = str(root / "database")

        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "backend"))
        from app.main import connect, init_db, scan_library

        init_db()
        with connect() as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES('source_folder',?)", (str(library),))

        scan = scan_library()
        with connect() as conn:
            paper = conn.execute("SELECT * FROM papers").fetchone()
            files = conn.execute(
                "SELECT filename,status,pages,file_type FROM source_files ORDER BY filename"
            ).fetchall()

        assert scan["found"] == 2, f"Expected 2 PDFs, found {scan['found']}"
        assert paper is not None, "No paper identity was created"
        assert paper["subject_code"] == "0580"
        assert paper["subject"] == "Mathematics"
        assert paper["year"] == 2026
        assert paper["season"] == "May/June"
        assert paper["paper_number"] == "11"
        assert paper["paper_level"] == "Core"
        assert paper["calculator"] == "Non-calculator"
        assert paper["pair_status"] == "paired"
        assert len(files) == 2 and all(row["status"] == "completed" for row in files)
        assert all(row["pages"] and row["pages"] > 0 for row in files)
        assert {row["file_type"] for row in files} == {"question_paper", "mark_scheme"}

        print(
            json.dumps(
                {
                    "result": "PASS",
                    "paper": {
                        "qualification": paper["qualification"],
                        "subject": paper["subject"],
                        "subject_code": paper["subject_code"],
                        "year": paper["year"],
                        "season": paper["season"],
                        "paper": paper["paper_number"],
                        "level": paper["paper_level"],
                        "calculator": paper["calculator"],
                        "pair_status": paper["pair_status"],
                    },
                    "files": [dict(row) for row in files],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
