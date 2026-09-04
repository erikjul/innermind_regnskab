"""Webapplikation (FastAPI). Start med: uvicorn app.main:app --reload"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import anthropic
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import backup, bookkeeping as bk, config, extraction, files, kontoplan, saft, vat
from .db import Base, SessionLocal, engine, get_db
from .models import Account, AuditLog, JournalEntry, JournalLine, PeriodLock, Settings, VatCode, VatSettlement, Voucher
from .money import fra_oere, til_oere

app = FastAPI(title="InnerMind Regnskab")
HER = Path(__file__).parent
app.mount("/static", StaticFiles(directory=HER / "static"), name="static")
templates = Jinja2Templates(directory=HER / "templates")
templates.env.filters["kr"] = fra_oere
templates.env.filters["dato"] = lambda d: d.strftime("%d.%m.%Y") if d else ""
templates.env.filters["tid"] = lambda d: d.strftime("%d.%m.%Y %H:%M") if d else ""
templates.env.filters["fromjson"] = json.loads

STATUS_TEKST = {"uploadet": "Uploadet", "aflaeser": "Aflæser…", "klar": "Klar til bogføring", "bogfoert": "Bogført",
                "fejl": "Aflæsning fejlede", "annulleret": "Annulleret"}
DOKUMENTTYPER = [("koebsfaktura", "Købsfaktura"), ("kvittering", "Kvittering (køb)"), ("kreditnota", "Kreditnota fra leverandør"),
                 ("salgsfaktura", "Salgsfaktura"), ("salgskreditnota", "Kreditnota til kunde"), ("andet", "Andet")]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BILAG_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        kontoplan.seed(s, Account, VatCode, Settings)
    yield


app.router.lifespan_context = lifespan


def render(request: Request, navn: str, db: Session, **ctx):
    ctx.setdefault("indstillinger", db.get(Settings, 1))
    ctx.setdefault("besked", request.query_params.get("besked"))
    ctx.setdefault("fejl", request.query_params.get("fejl"))
    ctx.setdefault("idag", date.today())
    ctx.setdefault("STATUS_TEKST", STATUS_TEKST)
    return templates.TemplateResponse(request, navn, ctx)


def redirect(url: str, besked: str | None = None, fejl: str | None = None):
    from urllib.parse import urlencode
    q = {k: v for k, v in {"besked": besked, "fejl": fejl}.items() if v}
    return RedirectResponse(url + ("?" + urlencode(q) if q else ""), status_code=303)


def _dato(s: str | None, standard: date | None = None) -> date | None:
    if not s:
        return standard
    try:
        return date.fromisoformat(s)
    except ValueError:
        for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
    raise HTTPException(400, f"Ugyldig dato: {s}")


def _konti(db: Session, kun_aktive=True) -> list[Account]:
    q = select(Account).order_by(Account.nummer)
    if kun_aktive:
        q = q.where(Account.aktiv.is_(True))
    return list(db.scalars(q))


def _momskoder(db: Session) -> list[VatCode]:
    return list(db.scalars(select(VatCode).where(VatCode.aktiv.is_(True))))


# --- Forside -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def forside(request: Request, db: Session = Depends(get_db)):
    s = db.get(Settings, 1)
    aar = date.today().year
    status = dict(db.execute(select(Voucher.status, func.count()).group_by(Voucher.status)).all())
    res = bk.resultatopgoerelse(db, date(aar, 1, 1), date(aar, 12, 31))
    perioder = vat.momsperioder(s, aar)
    aktuel = next((p for p in perioder if p[0] <= date.today() <= p[1]), perioder[-1])
    moms = vat.momsopgoerelse(db, aktuel[0], aktuel[1])
    seneste = list(db.scalars(select(Voucher).order_by(Voucher.id.desc()).limit(8)))
    ok, kaedefejl = bk.verificer_kaede(db)
    bal = bk.balance(db, date.today())
    bank = next((b for a, b in bal["aktiver"] if a.nummer == s.standard_bankkonto), 0)
    return render(request, "forside.html", db, status=status, res=res, moms=moms, periode=aktuel, seneste=seneste,
                  kaede_ok=ok, kaedefejl=kaedefejl, aar=aar, bank=bank)


# --- Bilag ---------------------------------------------------------------------

@app.get("/bilag", response_class=HTMLResponse)
def bilag_liste(request: Request, status: str = "", db: Session = Depends(get_db)):
    q = select(Voucher).order_by(Voucher.bilagsnr.desc())
    if status:
        q = q.where(Voucher.status == status)
    return render(request, "bilag_liste.html", db, bilag=list(db.scalars(q)), status=status)


@app.get("/bilag/upload", response_class=HTMLResponse)
def upload_form(request: Request, db: Session = Depends(get_db)):
    return render(request, "upload.html", db, api_ok=bool(_api_noegle()))


def _api_noegle() -> bool:
    import os
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _aflaes_job(bilag_id: int) -> None:
    """Baggrundsjob: aflæser bilaget med Claude og gemmer forslaget."""
    with SessionLocal() as db:
        v = db.get(Voucher, bilag_id)
        if v is None:
            return
        s = db.get(Settings, 1)
        try:
            v.status = "aflaeser"; db.commit()
            konti = _konti(db)
            momskoder = _momskoder(db)
            a = extraction.aflaes(files.laes_bilag(v.fil_sti), v.mime, firma=s.firmanavn, cvr=s.cvr,
                                  kontoplan=[(k.nummer, k.navn) for k in konti if k.er_drift or k.type == "aktiv"],
                                  momskoder=[(m.kode, m.navn) for m in momskoder])
            extraction.anvend_paa_bilag(v, a, {k.nummer for k in konti}, {m.kode for m in momskoder})
            if v.konto is None:
                # falder tilbage på kontoens standardmomskode / typisk konto
                v.konto = 3299 if v.dokumenttype not in ("salgsfaktura", "salgskreditnota") else 1010
            if v.momskode is None:
                k = db.get(Account, v.konto)
                v.momskode = k.standard_momskode if k else None
            v.modkonto = s.standard_bankkonto if v.betalt else (
                s.standard_debitorkonto if v.dokumenttype in ("salgsfaktura", "salgskreditnota") else s.standard_kreditorkonto)
            v.aflaest = datetime.now().replace(microsecond=0)
            v.aflaesning_model = config.CLAUDE_MODEL
            v.status = "klar"
            v.fejl = None
            bk.log(db, "bilag_aflaest", "bilag", v.id, {"sikkerhed": a.sikkerhed, "total": v.beloeb_total})
        except anthropic.AuthenticationError:
            v.status = "fejl"; v.fejl = "Ugyldig eller manglende ANTHROPIC_API_KEY. Indtast oplysningerne manuelt eller ret nøglen."
        except anthropic.RateLimitError:
            v.status = "fejl"; v.fejl = "API'et er midlertidigt overbelastet (rate limit). Prøv aflæsning igen om lidt."
        except anthropic.APIStatusError as e:
            v.status = "fejl"; v.fejl = f"API-fejl ({e.status_code}): {e.message}"
        except anthropic.APIConnectionError:
            v.status = "fejl"; v.fejl = "Kunne ikke forbinde til Claude API. Tjek internetforbindelsen."
        except Exception as e:  # noqa: BLE001
            v.status = "fejl"; v.fejl = f"Aflæsning fejlede: {e}"
        if v.status == "fejl":
            bk.log(db, "bilag_aflaesning_fejl", "bilag", v.id, v.fejl)
        db.commit()


@app.post("/bilag/upload")
async def upload(request: Request, bg: BackgroundTasks, filer: list[UploadFile] = File(...), kilde: str = Form("upload"),
                 db: Session = Depends(get_db)):
    oprettet, fejl = [], []
    for f in filer:
        if not f.filename:
            continue
        indhold = await f.read()
        try:
            nr = bk.naeste_bilagsnr(db)
            meta = files.gem_bilag(indhold, f.filename, nr)
            dublet = db.scalar(select(Voucher).where(Voucher.sha256 == meta["sha256"], Voucher.status != "annulleret"))
            v = Voucher(bilagsnr=nr, kilde=kilde if kilde in ("upload", "kamera") else "upload",
                        original_filnavn=f.filename, **meta)
            if dublet:
                v.noter = f"OBS: Filen er identisk med bilag {dublet.bilagsnr} – muligvis en dublet."
            db.add(v); db.flush()
            bk.log(db, "bilag_uploadet", "bilag", v.id, {"bilagsnr": nr, "fil": f.filename, "sha256": meta["sha256"], "kilde": v.kilde})
            db.commit()
            oprettet.append(v)
        except ValueError as e:
            db.rollback()
            fejl.append(f"{f.filename}: {e}")
    for v in oprettet:
        if _api_noegle():
            bg.add_task(_aflaes_job, v.id)
        else:
            v.status = "klar"; v.fejl = "Automatisk aflæsning er slået fra (ingen ANTHROPIC_API_KEY). Udfyld felterne manuelt."
            db.commit()
    if not oprettet:
        return redirect("/bilag/upload", fejl="; ".join(fejl) or "Ingen filer valgt.")
    besked = f"{len(oprettet)} bilag uploadet" + (" og sendes til aflæsning." if _api_noegle() else ".")
    if fejl:
        besked += " Fejl: " + "; ".join(fejl)
    if len(oprettet) == 1:
        return redirect(f"/bilag/{oprettet[0].id}", besked=besked)
    return redirect("/bilag", besked=besked)


@app.get("/bilag/{bilag_id}", response_class=HTMLResponse)
def bilag_vis(request: Request, bilag_id: int, db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    s = db.get(Settings, 1)
    aflaesning = json.loads(v.aflaesning_json) if v.aflaesning_json else None
    forslag = None
    if v.status in ("klar", "fejl", "uploadet") and v.beloeb_total and v.konto and v.momskode:
        vc = db.get(VatCode, v.momskode)
        if vc:
            total = v.beloeb_total
            if v.dokumenttype in ("salgsfaktura", "salgskreditnota"):
                forslag = vat.salgslinjer(v.konto, v.modkonto or s.standard_debitorkonto, -total if v.dokumenttype == "salgskreditnota" else total, vc, s, v.beskrivelse)
            else:
                forslag = vat.koebslinjer(v.konto, v.modkonto or s.standard_bankkonto, -total if v.dokumenttype == "kreditnota" else total, vc, s, v.beskrivelse)
    konti = {k.nummer: k for k in _konti(db)}
    return render(request, "bilag.html", db, v=v, konti=list(konti.values()), kontinavne=konti, momskoder=_momskoder(db),
                  aflaesning=aflaesning, forslag=forslag, dokumenttyper=DOKUMENTTYPER,
                  balancekonti=[k for k in konti.values() if k.type in ("aktiv", "passiv", "egenkapital")])


@app.get("/bilag/{bilag_id}/fil")
def bilag_fil(bilag_id: int, visning: int = 0, db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    data = files.laes_bilag(v.fil_sti)
    mime = v.mime
    if visning:
        data, mime = files.forhaandsvisning(data, mime)
    headers = {"Content-Disposition": f'inline; filename="{files.sikkert_filnavn(v.original_filnavn)}"'}
    return Response(data, media_type=mime, headers=headers)


@app.post("/bilag/{bilag_id}/gem")
def bilag_gem(bilag_id: int, dokumenttype: str = Form(...), modpart: str = Form(""), modpart_cvr: str = Form(""),
              fakturanr: str = Form(""), dato: str = Form(""), forfaldsdato: str = Form(""), beloeb_total: str = Form(""),
              beskrivelse: str = Form(""), konto: int = Form(...), momskode: str = Form(...), modkonto: int = Form(...),
              noter: str = Form(""), handling: str = Form("gem"), db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    if v.status == "bogfoert":
        return redirect(f"/bilag/{v.id}", fejl="Bilaget er bogført og kan ikke ændres. Tilbagefør posteringen først.")
    try:
        v.dokumenttype = dokumenttype
        v.modpart = modpart.strip() or None
        v.modpart_cvr = modpart_cvr.strip() or None
        v.fakturanr = fakturanr.strip() or None
        v.dato = _dato(dato)
        v.forfaldsdato = _dato(forfaldsdato)
        v.beloeb_total = til_oere(beloeb_total) if beloeb_total.strip() else None
        v.beskrivelse = beskrivelse.strip() or None
        v.konto, v.momskode, v.modkonto = konto, momskode, modkonto
        v.noter = noter.strip() or None
        if v.status in ("uploadet", "fejl"):
            v.status = "klar"
        bk.log(db, "bilag_rettet", "bilag", v.id, {"dato": v.dato, "total": v.beloeb_total, "konto": konto, "momskode": momskode})
        if handling == "bogfoer":
            if not v.dato:
                raise bk.BogfoeringsFejl("Angiv bilagsdato.")
            if not v.beloeb_total:
                raise bk.BogfoeringsFejl("Angiv beløb inkl. moms.")
            if v.valuta != "DKK":
                raise bk.BogfoeringsFejl(f"Bilaget er i {v.valuta}. Omregn beløbet til DKK og sæt valuta til DKK i noterne, før du bogfører.")
            tekst = v.beskrivelse or (v.modpart or "Bilag")
            e = bk.bogfoer_bilag(db, v, dato=v.dato, konto=konto, momskode=momskode, modkonto=modkonto,
                                 total=v.beloeb_total, tekst=tekst, dokumenttype=dokumenttype)
            db.commit()
            return redirect(f"/bilag/{v.id}", besked=f"Bilag {v.bilagsnr} bogført som postering nr. {e.loebenr}.")
        db.commit()
        return redirect(f"/bilag/{v.id}", besked="Ændringer gemt.")
    except (bk.BogfoeringsFejl, ValueError) as e:
        db.rollback()
        return redirect(f"/bilag/{v.id}", fejl=str(e))


@app.post("/bilag/{bilag_id}/valuta")
def bilag_valuta(bilag_id: int, beloeb_dkk: str = Form(...), kurs_note: str = Form(""), db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    try:
        gammel = f"{fra_oere(v.beloeb_total)} {v.valuta}"
        v.beloeb_total = til_oere(beloeb_dkk)
        v.valuta = "DKK"
        v.noter = ((v.noter or "") + f" Omregnet fra {gammel} til DKK. {kurs_note}").strip()
        bk.log(db, "bilag_valuta_omregnet", "bilag", v.id, {"fra": gammel, "til_dkk": v.beloeb_total, "note": kurs_note})
        db.commit()
        return redirect(f"/bilag/{v.id}", besked="Beløb omregnet til DKK.")
    except ValueError as e:
        return redirect(f"/bilag/{v.id}", fejl=str(e))


@app.post("/bilag/{bilag_id}/aflaes")
def bilag_aflaes_igen(bilag_id: int, bg: BackgroundTasks, db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    if v.status == "bogfoert":
        return redirect(f"/bilag/{v.id}", fejl="Bilaget er bogført.")
    if not _api_noegle():
        return redirect(f"/bilag/{v.id}", fejl="ANTHROPIC_API_KEY er ikke sat.")
    bg.add_task(_aflaes_job, v.id)
    return redirect(f"/bilag/{v.id}", besked="Bilaget aflæses igen – genindlæs siden om lidt.")


@app.post("/bilag/{bilag_id}/annuller")
def bilag_annuller(bilag_id: int, aarsag: str = Form(""), db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    if v.status == "bogfoert":
        return redirect(f"/bilag/{v.id}", fejl="Tilbagefør posteringen, før bilaget annulleres.")
    v.status = "annulleret"
    v.noter = ((v.noter or "") + f" Annulleret: {aarsag}").strip()
    bk.log(db, "bilag_annulleret", "bilag", v.id, {"aarsag": aarsag})
    db.commit()
    return redirect("/bilag", besked=f"Bilag {v.bilagsnr} annulleret (filen bevares).")


@app.get("/bilag/{bilag_id}/status")
def bilag_status(bilag_id: int, db: Session = Depends(get_db)):
    v = db.get(Voucher, bilag_id)
    if v is None:
        raise HTTPException(404)
    return {"status": v.status}


# --- Posteringer ---------------------------------------------------------------

@app.get("/posteringer", response_class=HTMLResponse)
def posteringer(request: Request, fra: str = "", til: str = "", db: Session = Depends(get_db)):
    q = select(JournalEntry).options(selectinload(JournalEntry.linjer), selectinload(JournalEntry.bilag)).order_by(JournalEntry.loebenr.desc())
    if fra:
        q = q.where(JournalEntry.dato >= _dato(fra))
    if til:
        q = q.where(JournalEntry.dato <= _dato(til))
    konti = {k.nummer: k for k in _konti(db, kun_aktive=False)}
    return render(request, "posteringer.html", db, posteringer=list(db.scalars(q).unique()), konti=konti, fra=fra, til=til)


@app.get("/posteringer/ny", response_class=HTMLResponse)
def postering_ny(request: Request, db: Session = Depends(get_db)):
    bilag = list(db.scalars(select(Voucher).where(Voucher.status == "klar").order_by(Voucher.bilagsnr.desc())))
    return render(request, "postering_ny.html", db, konti=_konti(db), momskoder=_momskoder(db), bilag=bilag)


@app.post("/posteringer/ny")
async def postering_opret(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        dato = _dato(form.get("dato"))
        tekst = form.get("tekst", "")
        bilag = db.get(Voucher, int(form["bilag_id"])) if form.get("bilag_id") else None
        linjer = []
        for i in range(0, 12):
            k = form.get(f"konto_{i}")
            if not k:
                continue
            linjer.append({"konto": int(k), "debet": til_oere(form.get(f"debet_{i}") or 0),
                           "kredit": til_oere(form.get(f"kredit_{i}") or 0), "momskode": form.get(f"momskode_{i}") or None,
                           "momsgrundlag": til_oere(form.get(f"grundlag_{i}") or 0), "tekst": form.get(f"tekst_{i}") or None})
        e = bk.opret_postering(db, dato, tekst, linjer, type="manuel", bilag=bilag)
        if bilag is not None:
            bilag.status = "bogfoert"; bilag.postering_id = e.id
        db.commit()
        return redirect(f"/posteringer/{e.id}", besked=f"Postering nr. {e.loebenr} oprettet.")
    except (bk.BogfoeringsFejl, ValueError, HTTPException) as e:
        db.rollback()
        return redirect("/posteringer/ny", fejl=getattr(e, "detail", None) or str(e))


@app.get("/posteringer/{entry_id}", response_class=HTMLResponse)
def postering_vis(request: Request, entry_id: int, db: Session = Depends(get_db)):
    e = db.get(JournalEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    konti = {k.nummer: k for k in _konti(db, kun_aktive=False)}
    return render(request, "postering.html", db, e=e, konti=konti,
                  storno_af=db.get(JournalEntry, e.storno_af_id) if e.storno_af_id else None,
                  storneret_af=db.get(JournalEntry, e.storneret_af_id) if e.storneret_af_id else None)


@app.post("/posteringer/{entry_id}/storno")
def postering_storno(entry_id: int, aarsag: str = Form(""), dato: str = Form(""), db: Session = Depends(get_db)):
    e = db.get(JournalEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    try:
        ny = bk.storno(db, e, _dato(dato, date.today()), aarsag)
        db.commit()
        return redirect(f"/posteringer/{ny.id}", besked=f"Postering nr. {e.loebenr} tilbageført med nr. {ny.loebenr}.")
    except bk.BogfoeringsFejl as ex:
        db.rollback()
        return redirect(f"/posteringer/{e.id}", fejl=str(ex))


# --- Kontoplan -------------------------------------------------------------------

@app.get("/kontoplan", response_class=HTMLResponse)
def kontoplan_vis(request: Request, db: Session = Depends(get_db)):
    s = bk.saldi(db, None, None)
    return render(request, "kontoplan.html", db, konti=_konti(db, kun_aktive=False), saldi=s, momskoder=_momskoder(db))


@app.post("/kontoplan")
def kontoplan_opret(nummer: int = Form(...), navn: str = Form(...), type: str = Form(...), gruppe: str = Form(""),
                    standard_momskode: str = Form(""), standardkonto: str = Form(""), db: Session = Depends(get_db)):
    if db.get(Account, nummer):
        a = db.get(Account, nummer)
        a.navn, a.type, a.gruppe = navn.strip(), type, gruppe.strip()
        a.standard_momskode, a.standardkonto = standard_momskode or None, standardkonto.strip() or None
        bk.log(db, "konto_rettet", "konto", nummer, {"navn": navn})
    else:
        db.add(Account(nummer=nummer, navn=navn.strip(), type=type, gruppe=gruppe.strip(),
                       standard_momskode=standard_momskode or None, standardkonto=standardkonto.strip() or None))
        bk.log(db, "konto_oprettet", "konto", nummer, {"navn": navn})
    db.commit()
    return redirect("/kontoplan", besked=f"Konto {nummer} gemt.")


@app.post("/kontoplan/{nummer}/aktiv")
def konto_aktiv(nummer: int, db: Session = Depends(get_db)):
    a = db.get(Account, nummer)
    if a is None:
        raise HTTPException(404)
    a.aktiv = not a.aktiv
    bk.log(db, "konto_aktiv_aendret", "konto", nummer, {"aktiv": a.aktiv})
    db.commit()
    return redirect("/kontoplan")


@app.get("/kontoplan/{nummer}", response_class=HTMLResponse)
def kontokort(request: Request, nummer: int, fra: str = "", til: str = "", db: Session = Depends(get_db)):
    a = db.get(Account, nummer)
    if a is None:
        raise HTTPException(404)
    rows = bk.kontokort(db, nummer, _dato(fra) if fra else None, _dato(til) if til else None)
    return render(request, "kontokort.html", db, konto=a, rows=rows, fra=fra, til=til)


# --- Moms ------------------------------------------------------------------------

@app.get("/moms", response_class=HTMLResponse)
def moms(request: Request, aar: int | None = None, fra: str = "", til: str = "", db: Session = Depends(get_db)):
    s = db.get(Settings, 1)
    aar = aar or date.today().year
    perioder = vat.momsperioder(s, aar)
    if fra and til:
        p_fra, p_til = _dato(fra), _dato(til)
    else:
        p_fra, p_til, _ = next((p for p in perioder if p[0] <= date.today() <= p[1]), perioder[-1])
    opg = vat.momsopgoerelse(db, p_fra, p_til)
    afregninger = list(db.scalars(select(VatSettlement).order_by(VatSettlement.fra.desc())))
    return render(request, "moms.html", db, opg=opg, perioder=perioder, aar=aar, felter=vat.ANGIVELSESFELTER,
                  rubrikker=vat.RUBRIKKER, afregninger=afregninger, valgt=(p_fra, p_til))


@app.post("/moms/afregn")
def moms_afregn(fra: str = Form(...), til: str = Form(...), db: Session = Depends(get_db)):
    try:
        e = bk.afregn_moms(db, _dato(fra), _dato(til))
        db.commit()
        return redirect(f"/moms?fra={fra}&til={til}", besked="Momsperioden er afregnet og låst." + (f" Postering nr. {e.loebenr}." if e else ""))
    except bk.BogfoeringsFejl as ex:
        db.rollback()
        return redirect(f"/moms?fra={fra}&til={til}", fejl=str(ex))


# --- Rapporter ----------------------------------------------------------------------

@app.get("/rapporter", response_class=HTMLResponse)
def rapporter(request: Request, fra: str = "", til: str = "", db: Session = Depends(get_db)):
    aar = date.today().year
    p_fra = _dato(fra, date(aar, 1, 1))
    p_til = _dato(til, date(aar, 12, 31))
    return render(request, "rapporter.html", db, res=bk.resultatopgoerelse(db, p_fra, p_til), bal=bk.balance(db, p_til),
                  fra=p_fra, til=p_til)


# --- Eksport, backup, kontrolspor ---------------------------------------------------------

@app.get("/eksport", response_class=HTMLResponse)
def eksport(request: Request, db: Session = Depends(get_db)):
    ok, fejl = bk.verificer_kaede(db)
    backups = sorted(config.BACKUP_DIR.glob("*.zip"), reverse=True) if config.BACKUP_DIR.exists() else []
    log = list(db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)))
    laase = list(db.scalars(select(PeriodLock).order_by(PeriodLock.fra)))
    return render(request, "eksport.html", db, kaede_ok=ok, kaedefejl=fejl, backups=[b.name for b in backups], log=log,
                  laase=laase, data_dir=str(config.DATA_DIR))


@app.get("/eksport/saft")
def eksport_saft(fra: str, til: str, db: Session = Depends(get_db)):
    xml = saft.generer_saft(db, _dato(fra), _dato(til))
    bk.log(db, "saft_eksporteret", "eksport", f"{fra}_{til}"); db.commit()
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="saft_{fra}_{til}.xml"'})


@app.get("/eksport/posteringer.csv")
def eksport_csv(db: Session = Depends(get_db)):
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Løbenr", "Dato", "Bilagsnr", "Tekst", "Type", "Konto", "Debet", "Kredit", "Momskode", "Momsgrundlag", "Linjetekst"])
    for e in db.scalars(select(JournalEntry).order_by(JournalEntry.loebenr)):
        for l in e.linjer:
            w.writerow([e.loebenr, e.dato.isoformat(), e.bilag.bilagsnr if e.bilag else "", e.tekst, e.type, l.konto,
                        fra_oere(l.debet), fra_oere(l.kredit), l.momskode or "", fra_oere(l.momsgrundlag), l.tekst or ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="posteringer.csv"'})


@app.post("/eksport/backup")
def eksport_backup(db: Session = Depends(get_db)):
    sti = backup.gem_backup(db)
    bk.log(db, "backup_oprettet", "backup", sti.name); db.commit()
    return redirect("/eksport", besked=f"Sikkerhedskopi gemt: {sti}")


@app.get("/eksport/backup/download")
def eksport_backup_download(db: Session = Depends(get_db)):
    data = backup.lav_backup(db)
    bk.log(db, "backup_downloadet", "backup", ""); db.commit()
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="regnskab_backup_{date.today()}.zip"'})


@app.post("/eksport/laas")
def laas(fra: str = Form(...), til: str = Form(...), aarsag: str = Form("Regnskabsperiode afsluttet"), db: Session = Depends(get_db)):
    bk.laas_periode(db, _dato(fra), _dato(til), aarsag); db.commit()
    return redirect("/eksport", besked="Perioden er låst.")


# --- Indstillinger ---------------------------------------------------------------

@app.get("/indstillinger", response_class=HTMLResponse)
def indstillinger(request: Request, db: Session = Depends(get_db)):
    return render(request, "indstillinger.html", db, konti=_konti(db), api_ok=_api_noegle(), model=config.CLAUDE_MODEL)


@app.post("/indstillinger")
async def indstillinger_gem(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    s = db.get(Settings, 1)
    for felt in ("firmanavn", "cvr", "adresse", "postnr", "by", "email", "telefon", "momsperiode"):
        setattr(s, felt, (form.get(felt) or "").strip())
    for felt in ("standard_bankkonto", "standard_kreditorkonto", "standard_debitorkonto", "koebsmoms_konto",
                 "salgsmoms_konto", "udlandsmoms_konto", "momsafregning_konto", "regnskabsaar_start_maaned"):
        if form.get(felt):
            setattr(s, felt, int(form[felt]))
    s.momsregistreret = bool(form.get("momsregistreret"))
    bk.log(db, "indstillinger_gemt", "indstillinger", 1, {k: v for k, v in form.items()})
    db.commit()
    return redirect("/indstillinger", besked="Indstillinger gemt.")
