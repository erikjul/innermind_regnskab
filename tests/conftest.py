import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="regnskab_test_")
os.environ["REGNSKAB_DATA_DIR"] = _tmp
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, kontoplan, main  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Account, Settings, VatCode  # noqa: E402


@pytest.fixture()
def db():
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(conn)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    kontoplan.seed(s, Account, VatCode, Settings)
    yield s
    s.close()


@pytest.fixture()
def bruger(db):
    u = auth.opret_bruger(db, "erik", "Erik Nielsen", "hemmelig-kode-123", admin=True)
    db.commit()
    return u


@pytest.fixture()
def client(db, bruger):
    """Logget ind som administrator."""
    with TestClient(main.app) as c:
        r = c.post("/login", data={"brugernavn": "erik", "kodeord": "hemmelig-kode-123"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        yield c
