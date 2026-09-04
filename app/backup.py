"""Sikkerhedskopi af database og bilag (bogføringsloven § 16, stk. 1, nr. 2 / § 12-13).

Zip-filen indeholder databasen, alle originale bilag og en JSON-eksport af posteringerne, så
regnskabsmaterialet kan genskabes uden dette program. Kopien bør gemmes hos en tredjepart
(fx en cloud-tjeneste) og opbevares i 5 år fra regnskabsårets udløb.
"""
import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Account, JournalEntry, VatCode, Voucher


def _db_kopi() -> bytes:
    """Konsistent kopi af SQLite-databasen (også under WAL)."""
    src = sqlite3.connect(str(config.DB_PATH))
    buf_path = config.DATA_DIR / ".backup_tmp.db"
    dst = sqlite3.connect(str(buf_path))
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    data = buf_path.read_bytes()
    buf_path.unlink(missing_ok=True)
    return data


def posteringer_json(session: Session) -> str:
    out = []
    for e in session.scalars(select(JournalEntry).order_by(JournalEntry.loebenr)):
        out.append({"loebenr": e.loebenr, "dato": e.dato.isoformat(), "tekst": e.tekst, "type": e.type,
                    "bilagsnr": e.bilag.bilagsnr if e.bilag else None, "oprettet": e.oprettet.isoformat(),
                    "hash": e.hash, "forrige_hash": e.forrige_hash,
                    "linjer": [{"konto": l.konto, "debet": l.debet, "kredit": l.kredit, "momskode": l.momskode,
                                "momsgrundlag": l.momsgrundlag, "tekst": l.tekst} for l in e.linjer]})
    return json.dumps(out, ensure_ascii=False, indent=1)


def lav_backup(session: Session) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if config.DB_PATH.exists():
            z.writestr("regnskab.db", _db_kopi())
        z.writestr("posteringer.json", posteringer_json(session))
        z.writestr("kontoplan.json", json.dumps([{"nummer": a.nummer, "navn": a.navn, "type": a.type, "gruppe": a.gruppe,
                                                  "standard_momskode": a.standard_momskode, "standardkonto": a.standardkonto}
                                                 for a in session.scalars(select(Account))], ensure_ascii=False, indent=1))
        z.writestr("momskoder.json", json.dumps([{"kode": v.kode, "navn": v.navn, "sats_promille": v.sats_promille,
                                                  "fradrag_pct": v.fradrag_pct} for v in session.scalars(select(VatCode))],
                                                ensure_ascii=False, indent=1))
        z.writestr("bilag.json", json.dumps([{"bilagsnr": v.bilagsnr, "fil": v.fil_sti, "sha256": v.sha256, "status": v.status,
                                              "modpart": v.modpart, "dato": v.dato.isoformat() if v.dato else None,
                                              "beloeb_total": v.beloeb_total, "fakturanr": v.fakturanr}
                                             for v in session.scalars(select(Voucher))], ensure_ascii=False, indent=1))
        if config.BILAG_DIR.exists():
            for p in sorted(config.BILAG_DIR.rglob("*")):
                if p.is_file():
                    z.write(p, str(p.relative_to(config.DATA_DIR)))
    return buf.getvalue()


def gem_backup(session: Session, behold: int = 30) -> Path:
    """Gemmer en ny zip i backup-mappen og beholder de seneste `behold` kopier."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    sti = config.BACKUP_DIR / f"backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
    sti.write_bytes(lav_backup(session))
    gamle = sorted(config.BACKUP_DIR.glob("backup_*.zip"))
    for g in gamle[:-behold] if behold > 0 else []:
        g.unlink(missing_ok=True)
    return sti


if __name__ == "__main__":  # python -m app.backup  (fx fra cron)
    from .db import SessionLocal
    with SessionLocal() as s:
        print(gem_backup(s))
