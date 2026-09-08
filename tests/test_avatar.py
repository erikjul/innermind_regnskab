import json

from app import avatar


def _events(tekst: str) -> list[tuple[str, dict]]:
    ud = []
    for blok in tekst.strip().split("\n\n"):
        ev, data = None, ""
        for linje in blok.split("\n"):
            if linje.startswith("event:"):
                ev = linje[6:].strip()
            elif linje.startswith("data:"):
                data += linje[5:].strip()
        ud.append((ev, json.loads(data)))
    return ud


def test_saetningsdeling():
    t = "Hello there! I was picked in 2026. It was on Aug. 25th, wasn't it? Yes"
    assert avatar.del_i_saetninger(t) == ["Hello there!", "I was picked in 2026.", "It was on Aug. 25th, wasn't it?", "Yes"]
    assert avatar.del_i_saetninger("Mr. Smith won.") == ["Mr. Smith won."]
    assert avatar.del_i_saetninger("Just a start with no end") == ["Just a start with no end"]
    assert avatar.del_i_saetninger("") == []


def test_historik_normaliseres():
    h = avatar.normaliser_historik([{"role": "assistant", "content": "hi"}, {"role": "system", "content": "x"},
                                    {"role": "user", "content": " Hello "}, {"role": "user", "content": "again"},
                                    "junk", {"role": "assistant", "content": ""}])
    assert h == [{"role": "user", "content": "Hello\nagain"}]
    lang = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(60)]
    assert len(avatar.normaliser_historik(lang)) == avatar.MAKS_HISTORIK


def test_persona_standard_og_egen(db):
    assert "Poppy Marlow" in avatar.laes_persona()
    avatar.gem_persona("# Persona\nYou are a test golfer.")
    assert avatar.laes_persona() == "# Persona\nYou are a test golfer."
    assert "Rules for the spoken medium" in avatar.systemprompt()
    avatar.persona_sti().unlink()
    assert "Poppy Marlow" in avatar.laes_persona()


def test_samtale_stroem_uden_stemme(monkeypatch):
    monkeypatch.setattr(avatar, "svar_stroem", lambda h, **kw: iter(["Hello!", "Nice to meet you."]))
    ev = _events("".join(avatar.samtale_stroem([{"role": "user", "content": "hi"}])))
    assert [e for e, _ in ev] == ["sentence", "sentence", "done"]
    assert ev[0][1] == {"text": "Hello!", "speech": None}
    assert ev[2][1]["text"] == "Hello! Nice to meet you."


def test_samtale_stroem_med_stemme_og_fejl(monkeypatch):
    monkeypatch.setattr(avatar, "svar_stroem", lambda h, **kw: iter(["One.", "Two."]))
    kald = []

    def stemme(t):
        kald.append(t)
        if t == "Two.":
            raise RuntimeError("ElevenLabs returned 401")
        return {"audio": "AAAA", "mime": "audio/mpeg", "chars": list(t), "starts": [0.0] * len(t), "ends": [0.1] * len(t)}

    ev = _events("".join(avatar.samtale_stroem([{"role": "user", "content": "hi"}], stemme=stemme)))
    assert [e for e, _ in ev] == ["sentence", "notice", "sentence", "done"]
    assert ev[0][1]["speech"]["audio"] == "AAAA" and ev[2][1]["speech"] is None
    assert "401" in ev[1][1]["message"]


def test_samtale_stroem_modelfejl(monkeypatch):
    def fejler(h, **kw):
        raise RuntimeError("The model declined to answer that.")
        yield  # noqa: unreachable – gør funktionen til en generator
    monkeypatch.setattr(avatar, "svar_stroem", fejler)
    ev = _events("".join(avatar.samtale_stroem([{"role": "user", "content": "hi"}])))
    assert ev == [("error", {"message": "The model declined to answer that."})]


def test_avatar_sider(client, monkeypatch):
    assert "Tap the microphone" in client.get("/avatar").text
    assert "Poppy Marlow" in client.get("/avatar/viden").text
    r = client.post("/avatar/viden", data={"tekst": "# Persona\nTest player"}, follow_redirects=False)
    assert "besked" in r.headers["location"]
    assert "Test player" in client.get("/avatar/viden").text
    r = client.post("/avatar/viden", data={"tekst": "", "handling": "nulstil"}, follow_redirects=False)
    assert "besked" in r.headers["location"] and not avatar.persona_sti().exists()
    # chat: uden API-nøgle får browseren en fejl-event i stedet for et svar
    r = client.post("/avatar/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert _events(r.text) == [("error", {"message": "ANTHROPIC_API_KEY is not set on the server."})]
    assert client.post("/avatar/api/chat", json={"messages": []}).status_code == 400
    # med nøgle (og en falsk model) streames sætninger
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(avatar, "svar_stroem", lambda h, **kw: iter(["Hello there.", "How are you?"]))
    r = client.post("/avatar/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert [e for e, _ in _events(r.text)] == ["sentence", "sentence", "done"]


def test_avatar_kraever_login(db):
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as c:
        assert c.get("/avatar", follow_redirects=False).status_code == 303
        assert c.post("/avatar/api/chat", json={"messages": []}).status_code == 401


def test_svar_stroem_buffer_og_afvisning():
    """Streamer sætninger løbende og afslutter med resten; en afvisning bliver til en fejl."""
    import contextlib
    import types

    class Stream:
        def __init__(self, bidder, stop="end_turn"):
            self.text_stream = iter(bidder); self.stop = stop
        def get_final_message(self):
            return types.SimpleNamespace(stop_reason=self.stop)

    def klient(bidder, stop="end_turn"):
        @contextlib.contextmanager
        def stream(**kw):
            assert kw["messages"] and "cache_control" in kw["system"][0]
            yield Stream(bidder, stop)
        return types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)))

    h = [{"role": "user", "content": "hi"}]
    bidder = ["Well, hel", "lo there! I'm **Poppy**. Lovely to", " meet you.", " What's your name"]
    assert list(avatar.svar_stroem(h, client=klient(bidder), persona="p")) == \
        ["Well, hello there!", "I'm Poppy.", "Lovely to meet you.", "What's your name"]
    import pytest
    with pytest.raises(RuntimeError, match="declined"):
        list(avatar.svar_stroem(h, client=klient(["Sorry."], stop="refusal"), persona="p"))


def _portraet(w=600, h=800) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 160, 140)).save(buf, format="PNG")
    return buf.getvalue()


def test_portraet_rig(client):
    assert client.get("/avatar/portraet.jpg").status_code == 404
    assert avatar.laes_rig() is None
    r = client.post("/avatar/portraet", files=[("fil", ("p.png", _portraet(1800, 2400), "image/png"))], follow_redirects=False)
    assert "besked" in r.headers["location"]
    rig = avatar.laes_rig()
    assert (rig["w"], rig["h"]) == (1050, 1400)          # nedskaleret til maks. 1400 px
    assert rig["mund"]["x"] == 525 and "version" in rig
    assert client.get("/avatar/portraet.jpg").headers["content-type"] == "image/jpeg"
    # avatar-siden og viden-siden bruger riggen
    assert 'data-rig=' in client.get("/avatar").text and "rigbeholder" in client.get("/avatar").text
    assert "Kalibrering" in client.get("/avatar/viden").text
    # kalibrering gemmes og valideres
    ny = {"mund": {"x": 500, "y": 900, "b": 180}, "oejne": {"v": {"x": 400, "y": 600, "b": 90}, "h": {"x": 600, "y": 600, "b": 90}}, "blink": False}
    r = client.post("/avatar/portraet/kalibrering", json=ny)
    assert r.status_code == 200 and r.json()["rig"]["mund"] == ny["mund"] and avatar.laes_rig()["blink"] is False
    r = client.post("/avatar/portraet/kalibrering", json={"mund": {"x": 5000, "y": 1, "b": 10}, "oejne": ny["oejne"]})
    assert r.status_code == 400 and "Munden" in r.json()["fejl"]
    assert client.post("/avatar/portraet/kalibrering", json={"mund": ny["mund"]}).status_code == 400
    # ugyldig fil
    r = client.post("/avatar/portraet", files=[("fil", ("x.png", b"ikke et billede", "image/png"))], follow_redirects=False)
    assert "fejl" in r.headers["location"]
    # slet
    r = client.post("/avatar/portraet/slet", follow_redirects=False)
    assert "besked" in r.headers["location"] and avatar.laes_rig() is None
    assert "rigbeholder" not in client.get("/avatar").text
