import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="regnskab_test_")
os.environ["REGNSKAB_DATA_DIR"] = _tmp
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

import pytest  # noqa: E402

from app import kontoplan  # noqa: E402
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
