"""Kommandolinje til brugere:  python -m app.users opret <brugernavn> [--admin]
                              python -m app.users kodeord <brugernavn>
                              python -m app.users liste"""
import getpass
import sys

from sqlalchemy import select

from . import auth
from .db import Base, SessionLocal, engine
from .models import User


def main(argv: list[str]) -> int:
    Base.metadata.create_all(engine)
    if not argv or argv[0] not in ("opret", "kodeord", "liste"):
        print(__doc__)
        return 1
    with SessionLocal() as s:
        if argv[0] == "liste":
            for u in s.scalars(select(User).order_by(User.brugernavn)):
                print(f"{u.brugernavn:20} {u.navn:30} {'admin' if u.admin else ''} {'' if u.aktiv else '(inaktiv)'}")
            return 0
        if len(argv) < 2:
            print("Angiv brugernavn."); return 1
        brugernavn = argv[1]
        kode = getpass.getpass("Adgangskode (mindst 10 tegn): ")
        if kode != getpass.getpass("Gentag adgangskode: "):
            print("Adgangskoderne er ikke ens."); return 1
        try:
            if argv[0] == "opret":
                navn = input("Fulde navn: ")
                auth.opret_bruger(s, brugernavn, navn, kode, admin="--admin" in argv)
                print(f"Bruger {brugernavn} oprettet.")
            else:
                u = s.scalar(select(User).where(User.brugernavn == brugernavn.lower()))
                if u is None:
                    print("Brugeren findes ikke."); return 1
                fejl = auth.valider_kodeord(kode)
                if fejl:
                    print(fejl); return 1
                u.kodeord_hash = auth.hash_kodeord(kode)
                print("Adgangskode ændret.")
            s.commit()
        except ValueError as e:
            print(e); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
