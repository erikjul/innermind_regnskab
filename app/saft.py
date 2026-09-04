"""SAF-T-eksport (Standard Audit File for Tax).

Bogføringsloven § 16 kræver, at et digitalt bogføringssystem kan eksportere bogføringen i
Erhvervsstyrelsens SAF-T-format. Denne eksport følger strukturen i OECD SAF-T 2.0 / dansk SAF-T
Financial (Header, MasterFiles, GeneralLedgerEntries). Valider filen mod Erhvervsstyrelsens
aktuelle XSD, inden den afleveres til en myndighed.
"""
from datetime import date, datetime
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, JournalEntry, Settings, VatCode
from .money import decimal_fra_oere
from .bookkeeping import saldi

NS = "urn:StandardAuditFile-Taxation-Financial:DK"


def _el(tag: str, vaerdi, indent: int = 0) -> str:
    if vaerdi is None or vaerdi == "":
        return ""
    return f"{'  ' * indent}<{tag}>{escape(str(vaerdi))}</{tag}>\n"


def _konto_type(a: Account) -> str:
    return {"indtaegt": "Revenue", "omkostning": "Expense", "aktiv": "Asset", "passiv": "Liability",
            "egenkapital": "Equity"}.get(a.type, "Other")


def generer_saft(session: Session, fra: date, til: date) -> str:
    s = session.get(Settings, 1)
    konti = list(session.scalars(select(Account).order_by(Account.nummer)))
    momskoder = list(session.scalars(select(VatCode)))
    dagen_foer = date.fromordinal(fra.toordinal() - 1)
    primo = saldi(session, None, dagen_foer)
    ultimo = saldi(session, None, til)
    entries = list(session.scalars(select(JournalEntry).where(JournalEntry.dato >= fra, JournalEntry.dato <= til)
                                   .order_by(JournalEntry.loebenr)))

    x = [f'<?xml version="1.0" encoding="UTF-8"?>\n<AuditFile xmlns="{NS}">\n', "  <Header>\n"]
    x.append(_el("AuditFileVersion", "1.0", 2))
    x.append(_el("AuditFileCountry", "DK", 2))
    x.append(_el("AuditFileDateCreated", date.today().isoformat(), 2))
    x.append(_el("SoftwareCompanyName", "InnerMind Regnskab", 2))
    x.append(_el("SoftwareID", "innermind_regnskab", 2))
    x.append(_el("SoftwareVersion", "1.0", 2))
    x.append("    <Company>\n")
    x.append(_el("RegistrationNumber", s.cvr, 3))
    x.append(_el("Name", s.firmanavn, 3))
    x.append("      <Address>\n")
    x.append(_el("StreetName", s.adresse, 4))
    x.append(_el("City", s.by, 4))
    x.append(_el("PostalCode", s.postnr, 4))
    x.append(_el("Country", "DK", 4))
    x.append("      </Address>\n    </Company>\n")
    x.append(_el("DefaultCurrencyCode", "DKK", 2))
    x.append("    <SelectionCriteria>\n")
    x.append(_el("SelectionStartDate", fra.isoformat(), 3))
    x.append(_el("SelectionEndDate", til.isoformat(), 3))
    x.append("    </SelectionCriteria>\n")
    x.append(_el("TaxAccountingBasis", "A", 2))
    x.append("  </Header>\n  <MasterFiles>\n    <GeneralLedgerAccounts>\n")
    for a in konti:
        p = primo.get(a.nummer, {}).get("saldo", 0)
        u = ultimo.get(a.nummer, {}).get("saldo", 0)
        x.append("      <Account>\n")
        x.append(_el("AccountID", a.nummer, 4))
        x.append(_el("AccountDescription", a.navn, 4))
        x.append(_el("StandardAccountID", a.standardkonto, 4))
        x.append(_el("GroupingCategory", _konto_type(a), 4))
        x.append(_el("GroupingCode", a.gruppe, 4))
        x.append(_el("AccountType", "GL", 4))
        x.append(_el("OpeningDebitBalance" if p >= 0 else "OpeningCreditBalance", decimal_fra_oere(abs(p)), 4))
        x.append(_el("ClosingDebitBalance" if u >= 0 else "ClosingCreditBalance", decimal_fra_oere(abs(u)), 4))
        x.append("      </Account>\n")
    x.append("    </GeneralLedgerAccounts>\n    <TaxTable>\n      <TaxTableEntry>\n")
    x.append(_el("TaxType", "MOMS", 4))
    x.append(_el("Description", "Moms", 4))
    for vc in momskoder:
        x.append("        <TaxCodeDetails>\n")
        x.append(_el("TaxCode", vc.kode, 5))
        x.append(_el("Description", vc.navn, 5))
        x.append(_el("TaxPercentage", decimal_fra_oere(vc.sats_promille * 10), 5))
        x.append(_el("Country", "DK", 5))
        x.append("        </TaxCodeDetails>\n")
    x.append("      </TaxTableEntry>\n    </TaxTable>\n  </MasterFiles>\n")
    x.append("  <GeneralLedgerEntries>\n")
    x.append(_el("NumberOfEntries", len(entries), 2))
    x.append(_el("TotalDebit", decimal_fra_oere(sum(e.sum_debet for e in entries)), 2))
    x.append(_el("TotalCredit", decimal_fra_oere(sum(e.sum_debet for e in entries)), 2))
    x.append("    <Journal>\n")
    x.append(_el("JournalID", "1", 3))
    x.append(_el("Description", "Kassekladde", 3))
    x.append(_el("Type", "GL", 3))
    for e in entries:
        x.append("      <Transaction>\n")
        x.append(_el("TransactionID", e.loebenr, 4))
        x.append(_el("Period", e.dato.month, 4))
        x.append(_el("PeriodYear", e.dato.year, 4))
        x.append(_el("TransactionDate", e.dato.isoformat(), 4))
        x.append(_el("SourceID", "bilag" if e.bilag_id else e.type, 4))
        x.append(_el("TransactionType", e.type, 4))
        x.append(_el("Description", e.tekst, 4))
        x.append(_el("SystemEntryDate", e.oprettet.isoformat(), 4))
        x.append(_el("GLPostingDate", e.dato.isoformat(), 4))
        if e.bilag:
            x.append(_el("SourceDocumentID", e.bilag.bilagsnr, 4))
        for i, l in enumerate(e.linjer, 1):
            x.append("        <Line>\n")
            x.append(_el("RecordID", f"{e.loebenr}-{i}", 5))
            x.append(_el("AccountID", l.konto, 5))
            x.append(_el("SourceDocumentID", e.bilag.bilagsnr if e.bilag else None, 5))
            x.append(_el("Description", l.tekst or e.tekst, 5))
            if l.debet:
                x.append(f"          <DebitAmount>\n{_el('Amount', decimal_fra_oere(l.debet), 6)}          </DebitAmount>\n")
            if l.kredit:
                x.append(f"          <CreditAmount>\n{_el('Amount', decimal_fra_oere(l.kredit), 6)}          </CreditAmount>\n")
            if l.momskode:
                x.append("          <TaxInformation>\n")
                x.append(_el("TaxType", "MOMS", 6))
                x.append(_el("TaxCode", l.momskode, 6))
                x.append(_el("TaxBase", decimal_fra_oere(l.momsgrundlag), 6))
                x.append("          </TaxInformation>\n")
            x.append("        </Line>\n")
        x.append("      </Transaction>\n")
    x.append("    </Journal>\n  </GeneralLedgerEntries>\n</AuditFile>\n")
    return "".join(x)
