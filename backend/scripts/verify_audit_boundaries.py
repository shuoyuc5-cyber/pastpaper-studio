"""Adversarial API regressions using disposable accounts and storage only."""
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="studio-audit-boundaries-") as temporary:
    os.environ["PASTPAPER_DATA_DIR"] = temporary
    os.environ["PASTPAPER_LAN_ONLY"] = "1"
    os.environ["PASTPAPER_LEGACY_GUEST_WRITES"] = "1"
    from app import main, studio, security

    def login_data(name):
        return {"email": f"{name}@example.test", "password": "audit-fixture-password"}

    def peer(octet):
        return {"x-forwarded-for": f"192.168.7.{octet}", "x-forwarded-host": "192.168.7.2:3000"}

    def client():
        return TestClient(main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))

    with client() as browser:
        assert browser.post("/api/auth/register", json={**login_data("admin"), "username": "admin"}).status_code == 200
        owner = dict(browser.cookies)
        assert browser.post("/api/admin/accounts", json={**login_data("student"), "username": "student"}).status_code == 201
        public = {'/api/health','/api/auth/me','/api/auth/login','/api/auth/register'}
        with client() as unsigned:
            for route in main.app.routes:
                if not isinstance(route, APIRoute) or route.path in public:
                    continue
                path=re.sub(r'\{[^}]+\}','1',route.path)
                for method in route.methods:
                    assert unsigned.request(method,path).status_code == 401, (method,path)

        failures = []
        def expect(condition, message):
            if not condition:
                failures.append(message)

        security.ATTEMPTS.clear()
        # One attacker can exhaust its source/account budget, but cannot lock out another source.
        with client() as anonymous, patch.object(studio, "verify_password", return_value=(False, None)):
            for _ in range(10):
                assert anonymous.post("/api/auth/login", headers=peer(7), json=login_data("student")).status_code == 401
            assert anonymous.post("/api/auth/login", headers=peer(7), json=login_data("student")).status_code == 429
        with client() as student:
            expect(student.post("/api/auth/login", headers=peer(8), json=login_data("student")).status_code == 200,
                   "a remote caller can exhaust another user's account budget")
            with patch.object(studio, "verify_password", return_value=(False, None)):
                for i in range(20):
                    expect(student.post("/api/auth/login", headers=peer(7),
                                        json=login_data(f"unknown-{i}")).status_code != 200, "invalid login succeeded")
            expect(student.post("/api/auth/login", headers=peer(9), json=login_data("student")).status_code == 200,
                   "one LAN source can exhaust the shared proxy login budget")

        def change_password_during_verification(_password, old_hash):
            import hashlib
            with main.connect() as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE username='student' AND password_hash=?",
                             ('changed-' + hashlib.sha256(old_hash.encode()).hexdigest(), old_hash))
            return True, None

        with client() as raced, patch.object(studio, 'verify_password', side_effect=change_password_during_verification):
            response = raced.post('/api/auth/login', headers=peer(10), json=login_data('student'))
            assert response.status_code == 401 and 'set-cookie' not in response.headers

        # PyMuPDF can recognize formats other than PDF even when filetype='pdf'.
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((30, 30), "Audit fixture")
            png = page.get_pixmap().tobytes("png")
            pdf = document.tobytes()
        with client() as guest:
            guest.cookies.update(owner)
            response = guest.post("/api/import/upload?filename=not-a-pdf.pdf", content=png)
            expect(response.status_code == 400, "a renamed image is accepted as a PDF")
            assert guest.post("/api/import/upload?filename=bad.pdf", content=b"%PDF-1.7\nnot a PDF").status_code == 400
            assert guest.post("/api/import/upload?filename=paper.pdf&relative_path=../paper.pdf", content=pdf).status_code == 400
            studio.UPLOAD_SLOTS.acquire()
            studio.UPLOAD_SLOTS.acquire()
            try:
                with patch.object(studio, 'bounded_body', side_effect=AssertionError('over-limit upload read the body')):
                    assert guest.post('/api/import/upload?filename=blocked.pdf',content=pdf).status_code == 429
                assert guest.get('/api/health').status_code == 200
            finally:
                studio.UPLOAD_SLOTS.release()
                studio.UPLOAD_SLOTS.release()

        # An on-disk link must not turn a previously shared PDF into a download of another file.
        folder = Path(temporary)
        source = folder / "owned.pdf"
        source.write_bytes(pdf)
        secret = folder / "secret.txt"
        secret.write_bytes(b"synthetic private content")
        source_id = "audit-owned"
        with main.connect() as conn:
            uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            conn.execute("""INSERT INTO source_files(id,path,filename,file_hash,status,added_at,updated_at,owner_id,visibility)
                            VALUES(?,?,?,?,'completed','now','now',?,'public')""",
                         (source_id, str(source), source.name, main.sha256_file(source), uid))
        assert browser.get(f"/api/files/{source_id}").content.startswith(b"%PDF-")
        source.unlink()
        source.symlink_to(secret)
        response = browser.get(f"/api/files/{source_id}")
        expect(response.status_code == 404 and secret.read_bytes() not in response.content,
               "shared PDF route follows a link into unrelated files")
        source.unlink()
        source.write_bytes(secret.read_bytes())
        response = browser.get(f"/api/files/{source_id}")
        expect(response.status_code == 404 and secret.read_bytes() not in response.content,
               "shared PDF route serves a replaced file without verifying its identity")
        source.write_bytes(pdf)
        response = browser.get(f"/api/files/{source_id}", headers={"Range": "bytes=1-10,20-30"})
        expect(response.status_code == 416, "multiple range requests accepted for PDF download")
        assert browser.get(f"/api/files/{source_id}", headers={"Range": "bytes=1-10"}).status_code == 206
        with main.connect() as conn:
            conn.execute('UPDATE source_files SET file_hash=NULL WHERE id=?', (source_id,))
        assert browser.get(f'/api/files/{source_id}').status_code == 404

        # File changes must also revoke the previous sharing consent after a scan.
        scanned = folder / "0580_s26_qp_11.pdf"
        with pymupdf.open() as document:
            document.new_page().insert_text((30,30),"a public test paper")
            document.save(scanned)
        with main.connect() as conn:
            conn.execute("INSERT INTO settings VALUES('source_folder',?)", (str(folder),))
        main.scan_library()
        with main.connect() as conn:
            paper_id = conn.execute("SELECT id FROM papers WHERE subject_code='0580'").fetchone()[0]
            conn.execute("""INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,
                         ms_segments,official_answer,official_guidance,topic_auto,difficulty,updated_at)
                         VALUES('audit-paper-question',?,'1','1',1,'fixture','[]','[]','[]','','','[]','easy','now')""",
                         (paper_id,))
        assert browser.put(f"/api/papers/{paper_id}/sharing",
                           json={"visibility":"public","rights_confirmed":True}).status_code == 200
        with pymupdf.open() as document:
            document.new_page().insert_text((30,30),"a different private document")
            document.save(scanned)
        main.scan_library()
        with main.connect() as conn:
            expect(conn.execute("SELECT visibility FROM papers WHERE id=?", (paper_id,)).fetchone()[0] == "private",
                   "rescan silently retains sharing consent for replacement PDF bytes")
            expect(conn.execute("SELECT visibility FROM source_files WHERE path=?", (str(scanned.resolve()),)).fetchone()[0] == "private",
                   "replaced PDF stays directly downloadable after rescan")

        if failures:
            raise AssertionError("; ".join(failures))
    print("PASS: login source isolation, upload signature/path checks, on-disk PDF identity and range limits")
