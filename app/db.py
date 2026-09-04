from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or config.DATABASE_URL
    if url.startswith("sqlite"):
        if not url.endswith(":memory:"):
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return eng
    return create_engine(url)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrer(eng=None) -> None:
    """Tilføjer kolonner, som er kommet til efter første version (SQLite kan ikke gøre det via create_all)."""
    from sqlalchemy import inspect, text
    eng = eng or engine
    nye = {"bilag": [("uploadet_af", "VARCHAR(60) DEFAULT ''")],
           "posteringer": [("oprettet_af", "VARCHAR(60) DEFAULT ''")],
           "kontrolspor": [("bruger", "VARCHAR(60) DEFAULT ''")]}
    insp = inspect(eng)
    with eng.begin() as conn:
        for tabel, kolonner in nye.items():
            if not insp.has_table(tabel):
                continue
            findes = {c["name"] for c in insp.get_columns(tabel)}
            for navn, typ in kolonner:
                if navn not in findes:
                    conn.execute(text(f"ALTER TABLE {tabel} ADD COLUMN {navn} {typ}"))
