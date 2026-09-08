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
