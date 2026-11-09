import os, tempfile
import app as m

def setup_module():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    m.DB_PATH = tmp.name
    m.init_db()

def test_login_page():
    client = m.app.test_client()
    r = client.get("/login")
    assert r.status_code == 200
    assert b"MediRefill" in r.data

def test_password_hash():
    h = m.pw_hash("safe-password")
    assert m.pw_ok("safe-password", h)
    assert not m.pw_ok("wrong", h)

def test_health():
    assert m.app.test_client().get("/health").json["status"] == "ok"
