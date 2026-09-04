from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, main
from app.models import AuditLog


def test_kodeord_hash():
    h = auth.hash_kodeord("hemmelig-kode-123")
    assert h.startswith("scrypt$") and auth.tjek_kodeord("hemmelig-kode-123", h)
    assert not auth.tjek_kodeord("forkert", h) and not auth.tjek_kodeord("x", "ugyldig")


def test_foerste_opsaetning_og_login(db):
    with TestClient(main.app) as c:
        # uden brugere sendes man til opsætning
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
        r = c.get("/login", follow_redirects=False)
        assert r.headers["location"] == "/opsaetning"
        r = c.post("/opsaetning", data={"brugernavn": "Lone", "navn": "Lone Møller", "kodeord": "kort", "kodeord2": "kort"}, follow_redirects=False)
        assert r.status_code == 200 and "mindst 10 tegn" in r.text
        r = c.post("/opsaetning", data={"brugernavn": "Lone", "navn": "Lone Møller", "kodeord": "lang-nok-kode-1", "kodeord2": "lang-nok-kode-1"}, follow_redirects=False)
        assert r.status_code == 303
        assert "lone" in c.get("/").text and "Log ud" in c.get("/").text  # logget ind
        # opsætning kan ikke køres igen
        assert c.get("/opsaetning", follow_redirects=False).headers["location"] == "/login"
        c.post("/logud")
        assert c.get("/bilag", follow_redirects=False).status_code == 303
        assert c.post("/bilag/1/annuller", data={}, follow_redirects=False).status_code == 401
        # forkert kodeord
        r = c.post("/login", data={"brugernavn": "lone", "kodeord": "forkert-kode-123"})
        assert "Forkert" in r.text
        r = c.post("/login", data={"brugernavn": "lone", "kodeord": "lang-nok-kode-1"}, follow_redirects=False)
        assert r.status_code == 303
        log = list(db.scalars(select(AuditLog).order_by(AuditLog.id)))
        assert any(l.handling == "login_fejlet" for l in log) and any(l.handling == "login" and l.bruger == "lone" for l in log)


def test_spaerring_efter_mange_forsoeg(db, bruger):
    auth._forsoeg.clear()
    with TestClient(main.app) as c:
        for _ in range(8):
            c.post("/login", data={"brugernavn": "erik", "kodeord": "forkert-kode-123"})
        r = c.post("/login", data={"brugernavn": "erik", "kodeord": "hemmelig-kode-123"})
        assert "For mange" in r.text
    auth._forsoeg.clear()


def test_brugeradministration(client, db):
    r = client.post("/brugere", data={"brugernavn": "lone", "navn": "Lone", "kodeord": "lones-kode-2026"}, follow_redirects=False)
    assert "besked" in r.headers["location"]
    assert "lone" in client.get("/brugere").text
    # almindelig bruger kan ikke administrere brugere
    with TestClient(main.app) as c2:
        c2.post("/login", data={"brugernavn": "lone", "kodeord": "lones-kode-2026"})
        assert c2.get("/brugere").status_code == 403
        assert "Brugere" not in c2.get("/").text.split("<main>")[0]
        assert c2.get("/bilag").status_code == 200
    # dublet brugernavn afvises
    r = client.post("/brugere", data={"brugernavn": "lone", "kodeord": "lones-kode-2026"}, follow_redirects=False)
    assert "fejl" in r.headers["location"]
    # deaktivering
    r = client.post("/brugere/2/aktiv", follow_redirects=False)
    assert "deaktiveret" in r.headers["location"]
    with TestClient(main.app) as c3:
        assert "Forkert" in c3.post("/login", data={"brugernavn": "lone", "kodeord": "lones-kode-2026"}).text
