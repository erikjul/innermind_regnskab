"""Datamodel. Alle beløb gemmes som heltal i øre for at undgå afrundingsfejl."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class Settings(Base):
    __tablename__ = "indstillinger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    firmanavn: Mapped[str] = mapped_column(String(200), default="")
    cvr: Mapped[str] = mapped_column(String(20), default="")
    adresse: Mapped[str] = mapped_column(String(200), default="")
    postnr: Mapped[str] = mapped_column(String(10), default="")
    by: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    telefon: Mapped[str] = mapped_column(String(50), default="")
    regnskabsaar_start_maaned: Mapped[int] = mapped_column(Integer, default=1)
    momsperiode: Mapped[str] = mapped_column(String(20), default="kvartal")  # maaned | kvartal | halvaar
    momsregistreret: Mapped[bool] = mapped_column(Boolean, default=True)
    standard_bankkonto: Mapped[int] = mapped_column(Integer, default=5520)
    standard_kreditorkonto: Mapped[int] = mapped_column(Integer, default=6110)
    standard_debitorkonto: Mapped[int] = mapped_column(Integer, default=5510)
    koebsmoms_konto: Mapped[int] = mapped_column(Integer, default=5610)
    salgsmoms_konto: Mapped[int] = mapped_column(Integer, default=6210)
    udlandsmoms_konto: Mapped[int] = mapped_column(Integer, default=6220)
    momsafregning_konto: Mapped[int] = mapped_column(Integer, default=6230)


class User(Base):
    __tablename__ = "brugere"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brugernavn: Mapped[str] = mapped_column(String(60), unique=True)
    navn: Mapped[str] = mapped_column(String(120), default="")
    kodeord_hash: Mapped[str] = mapped_column(String(200))
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    oprettet: Mapped[datetime] = mapped_column(DateTime, default=now)
    sidst_logget_ind: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Account(Base):
    __tablename__ = "konti"
    nummer: Mapped[int] = mapped_column(Integer, primary_key=True)
    navn: Mapped[str] = mapped_column(String(200))
    # indtaegt | omkostning | aktiv | passiv | egenkapital
    type: Mapped[str] = mapped_column(String(20))
    gruppe: Mapped[str] = mapped_column(String(100), default="")
    standard_momskode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    standardkonto: Mapped[str | None] = mapped_column(String(20), nullable=True)  # reference til Erhvervsstyrelsens standardkontoplan
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def er_drift(self) -> bool:
        return self.type in ("indtaegt", "omkostning")


class VatCode(Base):
    __tablename__ = "momskoder"
    kode: Mapped[str] = mapped_column(String(20), primary_key=True)
    navn: Mapped[str] = mapped_column(String(200))
    retning: Mapped[str] = mapped_column(String(10))  # koeb | salg | ingen
    sats_promille: Mapped[int] = mapped_column(Integer, default=0)  # 250 = 25 %
    fradrag_pct: Mapped[int] = mapped_column(Integer, default=100)  # andel af momsen der kan fradrages
    omvendt_betalingspligt: Mapped[bool] = mapped_column(Boolean, default=False)
    # felt på momsangivelsen for selve momsbeløbet: salgsmoms | koebsmoms | moms_varekoeb_udland | moms_ydelseskoeb_udland | None
    angivelsesfelt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # rubrik for grundlaget: A_varer | A_ydelser | B_varer | B_ydelser | C | None
    rubrik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Voucher(Base):
    """Et bilag (faktura, kvittering, kreditnota) – det originale dokument bevares uændret."""
    __tablename__ = "bilag"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bilagsnr: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="uploadet")  # uploadet | aflaeser | klar | bogfoert | fejl | annulleret
    kilde: Mapped[str] = mapped_column(String(20), default="upload")  # upload | kamera
    original_filnavn: Mapped[str] = mapped_column(String(300))
    fil_sti: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    stoerrelse: Mapped[int] = mapped_column(Integer)
    uploadet: Mapped[datetime] = mapped_column(DateTime, default=now)
    uploadet_af: Mapped[str] = mapped_column(String(60), default="")
    aflaest: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    aflaesning_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    aflaesning_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fejl: Mapped[str | None] = mapped_column(Text, nullable=True)

    # felter fra aflæsning – kan rettes af brugeren inden bogføring
    dokumenttype: Mapped[str | None] = mapped_column(String(30), nullable=True)  # koebsfaktura | salgsfaktura | kvittering | kreditnota | andet
    modpart: Mapped[str | None] = mapped_column(String(200), nullable=True)
    modpart_cvr: Mapped[str | None] = mapped_column(String(30), nullable=True)
    modpart_land: Mapped[str | None] = mapped_column(String(5), nullable=True)
    fakturanr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dato: Mapped[date | None] = mapped_column(Date, nullable=True)
    forfaldsdato: Mapped[date | None] = mapped_column(Date, nullable=True)
    valuta: Mapped[str] = mapped_column(String(3), default="DKK")
    beloeb_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # øre, inkl. moms
    beloeb_moms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beloeb_netto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beskrivelse: Mapped[str | None] = mapped_column(String(500), nullable=True)
    konto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    momskode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modkonto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    betalt: Mapped[bool] = mapped_column(Boolean, default=True)
    noter: Mapped[str | None] = mapped_column(Text, nullable=True)

    postering_id: Mapped[int | None] = mapped_column(ForeignKey("posteringer.id", use_alter=True, name="fk_bilag_postering"), nullable=True)
    postering: Mapped["JournalEntry | None"] = relationship(foreign_keys=[postering_id])


class JournalEntry(Base):
    """En postering. Posteringer kan aldrig ændres eller slettes – kun tilbageføres (storno)."""
    __tablename__ = "posteringer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loebenr: Mapped[int] = mapped_column(Integer, unique=True)
    dato: Mapped[date] = mapped_column(Date)
    tekst: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(20), default="normal")  # normal | storno | momsafregning | primo | manuel
    bilag_id: Mapped[int | None] = mapped_column(ForeignKey("bilag.id"), nullable=True)
    bilag: Mapped["Voucher | None"] = relationship(foreign_keys=[bilag_id], post_update=True)
    storno_af_id: Mapped[int | None] = mapped_column(ForeignKey("posteringer.id"), nullable=True)
    storneret_af_id: Mapped[int | None] = mapped_column(ForeignKey("posteringer.id"), nullable=True)
    oprettet: Mapped[datetime] = mapped_column(DateTime, default=now)
    oprettet_af: Mapped[str] = mapped_column(String(60), default="")
    forrige_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")
    linjer: Mapped[list["JournalLine"]] = relationship(back_populates="postering", cascade="all, delete-orphan", order_by="JournalLine.id")

    @property
    def er_storneret(self) -> bool:
        return self.storneret_af_id is not None

    @property
    def sum_debet(self) -> int:
        return sum(l.debet for l in self.linjer)


class JournalLine(Base):
    __tablename__ = "posteringslinjer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    postering_id: Mapped[int] = mapped_column(ForeignKey("posteringer.id"))
    postering: Mapped[JournalEntry] = relationship(back_populates="linjer")
    konto: Mapped[int] = mapped_column(ForeignKey("konti.nummer"))
    debet: Mapped[int] = mapped_column(Integer, default=0)  # øre
    kredit: Mapped[int] = mapped_column(Integer, default=0)  # øre
    momskode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    momsgrundlag: Mapped[int] = mapped_column(Integer, default=0)  # øre; det momspligtige grundlag (bruges til rubrikker)
    tekst: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @property
    def netto(self) -> int:
        return self.debet - self.kredit


class PeriodLock(Base):
    __tablename__ = "periodelaase"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fra: Mapped[date] = mapped_column(Date)
    til: Mapped[date] = mapped_column(Date)
    aarsag: Mapped[str] = mapped_column(String(300))
    oprettet: Mapped[datetime] = mapped_column(DateTime, default=now)


class VatSettlement(Base):
    __tablename__ = "momsafregninger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fra: Mapped[date] = mapped_column(Date)
    til: Mapped[date] = mapped_column(Date)
    felter_json: Mapped[str] = mapped_column(Text)
    postering_id: Mapped[int | None] = mapped_column(ForeignKey("posteringer.id"), nullable=True)
    oprettet: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("fra", "til"),)


class AuditLog(Base):
    """Kontrolspor: alle handlinger logges (Bogføringslovens § 4 og § 8)."""
    __tablename__ = "kontrolspor"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tid: Mapped[datetime] = mapped_column(DateTime, default=now)
    bruger: Mapped[str] = mapped_column(String(60), default="")
    handling: Mapped[str] = mapped_column(String(60))
    entitet: Mapped[str] = mapped_column(String(40))
    entitet_id: Mapped[str] = mapped_column(String(40), default="")
    detaljer: Mapped[str] = mapped_column(Text, default="")
