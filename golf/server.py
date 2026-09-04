"""
Golfturnering – lille webapp til løbende Stableford-stilling over tre runder.

Alle med adressen kan tilmelde sig, taste slag hul for hul og følge ranglisten.
Alt gemmes i én JSON-fil (GOLF_DATA_DIR/golf.json). Selve regnearbejdet (Stableford,
spillehandicap og turneringspoint) sker i browseren, se static/scoring.js.

Kør lokalt:  python -m uvicorn golf.server:app --host 0.0.0.0 --port 8010
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HER = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("GOLF_DATA_DIR", HER / "data"))
DATA_FIL = DATA_DIR / "golf.json"
PIN = os.environ.get("GOLF_PIN", "").strip()

ANTAL_RUNDER = 3

# Standardbane: par 72 med en almindelig fordeling af handicapnøgler. Rettes under Opsætning.
STANDARD_PAR = [4, 4, 3, 5, 4, 4, 3, 5, 4, 4, 5, 3, 4, 4, 5, 3, 4, 4]
STANDARD_SI = [7, 3, 15, 11, 1, 13, 17, 9, 5, 8, 12, 18, 2, 14, 10, 16, 4, 6]
RUNDER = [
    ("2026-09-18", "Fredag"),
    ("2026-09-19", "Lørdag"),
    ("2026-09-20", "Søndag"),
]


def standard_state() -> dict[str, Any]:
    return {
        "version": 1,
        "settings": {
            "name": "Golfturnering 2026",
            "allowance": 100,
            "rounds": [
                {
                    "date": d,
                    "label": lab,
                    "course": "",
                    "tee": "",
                    "cr": 72.0,
                    "slope": 113,
                    "par": list(STANDARD_PAR),
                    "si": list(STANDARD_SI),
                    "closed": False,
                }
                for d, lab in RUNDER
            ],
        },
        "players": [],
        "scores": {str(i): {} for i in range(ANTAL_RUNDER)},
    }


class Lager:
    """Hele turneringens tilstand i hukommelsen, skrevet atomisk til disk ved hver ændring."""

    def __init__(self, fil: Path):
        self.fil = fil
        self.lock = threading.Lock()
        self.state = self._laes()

    def _laes(self) -> dict[str, Any]:
        if self.fil.exists():
            with open(self.fil, encoding="utf-8") as f:
                state = json.load(f)
            grund = standard_state()
            # Manglende felter (fx efter en opdatering af programmet) udfyldes med standardværdier
            state.setdefault("version", 1)
            state.setdefault("players", [])
            state.setdefault("scores", grund["scores"])
            for i in range(ANTAL_RUNDER):
                state["scores"].setdefault(str(i), {})
            s = state.setdefault("settings", grund["settings"])
            s.setdefault("name", grund["settings"]["name"])
            s.setdefault("allowance", 100)
            runder = s.setdefault("rounds", [])
            while len(runder) < ANTAL_RUNDER:
                runder.append(grund["settings"]["rounds"][len(runder)])
            for r, g in zip(runder, grund["settings"]["rounds"]):
                for k, v in g.items():
                    r.setdefault(k, v)
            return state
        return standard_state()

    def gem(self) -> None:
        self.state["version"] += 1
        self.fil.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fil.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.fil)


lager = Lager(DATA_FIL)
app = FastAPI(title="Golfturnering", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HER / "static"), name="static")


# ---------- hjælpere ----------


def kraev_pin(pin: str | None) -> None:
    if PIN and not (pin and secrets.compare_digest(pin, PIN)):
        raise HTTPException(401, "Forkert eller manglende PIN")


def find_spiller(pid: str) -> dict[str, Any]:
    for p in lager.state["players"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, "Spilleren findes ikke")


def tjek_runde(r: int) -> None:
    if not 0 <= r < ANTAL_RUNDER:
        raise HTTPException(404, "Runden findes ikke")


def rens_navn(navn: str) -> str:
    navn = re.sub(r"\s+", " ", navn or "").strip()
    if not 1 <= len(navn) <= 60:
        raise HTTPException(422, "Navnet skal være mellem 1 og 60 tegn")
    return navn


def tjek_hcp(hcp: float) -> float:
    if not -10 <= hcp <= 54:
        raise HTTPException(422, "HCP-index skal ligge mellem -10 og 54")
    return round(float(hcp), 1)


# ---------- modeller ----------


class NySpiller(BaseModel):
    name: str
    hcp: float


class RetSpiller(BaseModel):
    name: str | None = None
    hcp: float | None = None
    absent: list[bool] | None = None


class Slag(BaseModel):
    # None = ryd hullet, 0 = streget (hullet opgivet), ellers antal slag
    strokes: int | None = Field(default=None, ge=0, le=30)


class Runde(BaseModel):
    date: str
    label: str
    course: str = ""
    tee: str = ""
    cr: float = Field(ge=40, le=90)
    slope: int = Field(ge=55, le=155)
    par: list[int]
    si: list[int]
    closed: bool = False


class Opsaetning(BaseModel):
    name: str
    allowance: int = Field(ge=50, le=100)
    rounds: list[Runde]


# ---------- sider ----------


@app.get("/", include_in_schema=False)
def forside() -> FileResponse:
    return FileResponse(HER / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sundhed")
def sundhed() -> dict[str, str]:
    return {"status": "ok"}


# ---------- api ----------


@app.get("/api/state")
def hent_state(since: int = 0) -> JSONResponse:
    with lager.lock:
        if since and since == lager.state["version"]:
            return JSONResponse({"unchanged": True, "version": since, "pinRequired": bool(PIN)})
        body = dict(lager.state)
    body["pinRequired"] = bool(PIN)
    body["serverTime"] = time.time()
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.post("/api/players", status_code=201)
def opret_spiller(data: NySpiller) -> dict[str, Any]:
    navn = rens_navn(data.name)
    hcp = tjek_hcp(data.hcp)
    with lager.lock:
        if any(p["name"].casefold() == navn.casefold() for p in lager.state["players"]):
            raise HTTPException(409, "Der er allerede en spiller med det navn")
        spiller = {
            "id": "p" + secrets.token_hex(4),
            "name": navn,
            "hcp": hcp,
            "absent": [False] * ANTAL_RUNDER,
            "created": time.time(),
        }
        lager.state["players"].append(spiller)
        lager.gem()
        return {"player": spiller, "version": lager.state["version"]}


@app.put("/api/players/{pid}")
def ret_spiller(pid: str, data: RetSpiller) -> dict[str, Any]:
    with lager.lock:
        p = find_spiller(pid)
        if data.name is not None:
            navn = rens_navn(data.name)
            if any(q["id"] != pid and q["name"].casefold() == navn.casefold() for q in lager.state["players"]):
                raise HTTPException(409, "Der er allerede en spiller med det navn")
            p["name"] = navn
        if data.hcp is not None:
            p["hcp"] = tjek_hcp(data.hcp)
        if data.absent is not None:
            if len(data.absent) != ANTAL_RUNDER:
                raise HTTPException(422, "absent skal have én værdi pr. runde")
            p["absent"] = [bool(x) for x in data.absent]
        lager.gem()
        return {"player": p, "version": lager.state["version"]}


@app.delete("/api/players/{pid}")
def slet_spiller(pid: str, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    kraev_pin(x_golf_pin)
    with lager.lock:
        find_spiller(pid)
        lager.state["players"] = [p for p in lager.state["players"] if p["id"] != pid]
        for runde in lager.state["scores"].values():
            runde.pop(pid, None)
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.put("/api/scores/{r}/{pid}/{hul}")
def gem_slag(r: int, pid: str, hul: int, data: Slag) -> dict[str, Any]:
    tjek_runde(r)
    if not 1 <= hul <= 18:
        raise HTTPException(404, "Hullet findes ikke")
    with lager.lock:
        find_spiller(pid)
        if lager.state["settings"]["rounds"][r]["closed"]:
            raise HTTPException(409, "Runden er lukket, så der kan ikke tastes flere scorer")
        kort = lager.state["scores"][str(r)].setdefault(pid, [None] * 18)
        kort[hul - 1] = data.strokes
        if all(s is None for s in kort):
            del lager.state["scores"][str(r)][pid]
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.put("/api/settings")
def gem_opsaetning(data: Opsaetning, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    kraev_pin(x_golf_pin)
    if len(data.rounds) != ANTAL_RUNDER:
        raise HTTPException(422, f"Der skal være {ANTAL_RUNDER} runder")
    for rd in data.rounds:
        if len(rd.par) != 18 or any(not 3 <= p <= 6 for p in rd.par):
            raise HTTPException(422, "Par skal angives for 18 huller (3–6)")
        if sorted(rd.si) != list(range(1, 19)):
            raise HTTPException(422, "Handicapnøglerne skal være tallene 1–18, hver brugt én gang")
    with lager.lock:
        lager.state["settings"] = {
            "name": rens_navn(data.name),
            "allowance": data.allowance,
            "rounds": [rd.model_dump() for rd in data.rounds],
        }
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.post("/api/rounds/{r}/closed")
def luk_runde(r: int, request: Request, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    tjek_runde(r)
    kraev_pin(x_golf_pin)
    closed = request.query_params.get("value", "1") not in ("0", "false")
    with lager.lock:
        lager.state["settings"]["rounds"][r]["closed"] = closed
        lager.gem()
        return {"ok": True, "closed": closed, "version": lager.state["version"]}


@app.post("/api/reset")
def nulstil(x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    """Sletter alle spillere og scorer, men beholder baneopsætningen. Kræver PIN, hvis en er sat."""
    kraev_pin(x_golf_pin)
    with lager.lock:
        lager.state["players"] = []
        lager.state["scores"] = {str(i): {} for i in range(ANTAL_RUNDER)}
        for rd in lager.state["settings"]["rounds"]:
            rd["closed"] = False
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}
