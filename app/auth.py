"""Login, brugere og adgangskontrol.

* Adgangskoder gemmes som scrypt-hash (Python-standardbibliotek, ingen ekstra afhængigheder).
* Sessionen ligger i en signeret cookie (Starlette SessionMiddleware).
* Den aktuelle bruger gemmes i en ContextVar, så kontrolsporet kan registrere, hvem der gjorde hvad.
* Gentagne mislykkede logins fra samme adresse spærres midlertidigt.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User

aktuel_bruger: contextvars.ContextVar[str] = contextvars.ContextVar("aktuel_bruger", default="system")

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024}
_MAKS_FORSOEG = 8
_SPAERRING_SEK = 15 * 60
_forsoeg: dict[str, list[float]] = {}


def hash_kodeord(kodeord: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(kodeord.encode("utf-8"), salt=salt, **_SCRYPT, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def tjek_kodeord(kodeord: str, gemt: str) -> bool:
    try:
        _, salt_b64, h_b64 = gemt.split("$")
        salt, h = base64.b64decode(salt_b64), base64.b64decode(h_b64)
    except (ValueError, TypeError):
        return False
    ny = hashlib.scrypt(kodeord.encode("utf-8"), salt=salt, **_SCRYPT, dklen=32)
    return hmac.compare_digest(ny, h)


def valider_kodeord(kodeord: str) -> str | None:
    if len(kodeord) < 10:
        return "Adgangskoden skal være mindst 10 tegn."
    return None


def opret_bruger(session: Session, brugernavn: str, navn: str, kodeord: str, admin: bool = False) -> User:
    brugernavn = brugernavn.strip().lower()
    if not brugernavn or not brugernavn.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValueError("Brugernavnet må kun indeholde bogstaver, tal, punktum, bindestreg og understreg.")
    if session.scalar(select(User).where(User.brugernavn == brugernavn)):
        raise ValueError(f"Brugernavnet '{brugernavn}' findes allerede.")
    fejl = valider_kodeord(kodeord)
    if fejl:
        raise ValueError(fejl)
    u = User(brugernavn=brugernavn, navn=navn.strip() or brugernavn, kodeord_hash=hash_kodeord(kodeord), admin=admin)
    session.add(u)
    session.flush()
    return u


def antal_brugere(session: Session) -> int:
    return session.scalar(select(__import__("sqlalchemy").func.count()).select_from(User)) or 0


def _ryd(ip: str) -> list[float]:
    nu = time.time()
    liste = [t for t in _forsoeg.get(ip, []) if nu - t < _SPAERRING_SEK]
    _forsoeg[ip] = liste
    return liste


def er_spaerret(ip: str) -> bool:
    return len(_ryd(ip)) >= _MAKS_FORSOEG


def registrer_fejl(ip: str) -> None:
    _ryd(ip).append(time.time())


def nulstil_forsoeg(ip: str) -> None:
    _forsoeg.pop(ip, None)


def log_ind(session: Session, brugernavn: str, kodeord: str, ip: str) -> User | None:
    if er_spaerret(ip):
        return None
    u = session.scalar(select(User).where(User.brugernavn == brugernavn.strip().lower(), User.aktiv.is_(True)))
    if u is None or not tjek_kodeord(kodeord, u.kodeord_hash):
        registrer_fejl(ip)
        return None
    nulstil_forsoeg(ip)
    u.sidst_logget_ind = datetime.now().replace(microsecond=0)
    return u


def session_hemmelighed() -> str:
    """Nøgle til signering af session-cookien. Sæt REGNSKAB_SESSION_SECRET fast i produktion."""
    from . import config
    hem = os.environ.get("REGNSKAB_SESSION_SECRET")
    if hem:
        return hem
    sti = config.DATA_DIR / ".session_secret"
    try:
        if sti.exists():
            return sti.read_text().strip()
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        ny = secrets.token_urlsafe(48)
        sti.write_text(ny)
        return ny
    except OSError:
        return secrets.token_urlsafe(48)
