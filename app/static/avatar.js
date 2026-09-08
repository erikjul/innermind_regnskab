// Samtale-avatar: talegenkendelse i browseren -> /avatar/api/chat (SSE) -> lyd + lip-sync på den tegnede figur.
(() => {
  const scene = document.getElementById('scene');
  const status = document.getElementById('status');
  const transskript = document.getElementById('transskript');
  const mic = document.getElementById('mic');
  const tekstform = document.getElementById('tekstform');
  const tekstfelt = document.getElementById('tekst');
  const haandfri = document.getElementById('haandfri');
  const lyd = document.getElementById('lyd');

  const historik = [];          // {role, content} – sendes med hver gang (serveren er stateless)
  let tilstand = 'idle';        // idle | listening | thinking | talking
  let koe = [];                 // sætninger der venter på at blive sagt
  let afspiller = false;
  let stroemFaerdig = true;
  let svarBoble = null;
  let genkender = null;
  let lydLaastOp = false;
  let stopSignal = null;        // AbortController for den igangværende forespørgsel
  let afbrydTale = null;        // afslutter den sætning, der er i gang, når brugeren afbryder

  // ---------- Hjælpere ----------
  const saetTilstand = (t, tekst) => {
    tilstand = t; scene.dataset.state = t;
    mic.classList.toggle('lytter', t === 'listening');
    mic.classList.toggle('taenker', t === 'thinking');
    if (tekst !== undefined) status.textContent = tekst;
  };
  // Uploadet portræt (rig) eller den tegnede figur
  let rig = null;
  if (scene.dataset.rig && window.AvatarRig) {
    try { rig = window.AvatarRig(document.getElementById('rigbeholder'), JSON.parse(scene.dataset.rig), scene.dataset.portraet); } catch (e) { rig = null; }
  }
  const mund = f => { scene.dataset.mouth = f; if (rig) rig.mund(f); };
  const boble = (klasse, tekst) => {
    const el = document.createElement('div');
    el.className = 'av-boble ' + klasse; el.textContent = tekst;
    transskript.appendChild(el); transskript.scrollTop = transskript.scrollHeight;
    return el;
  };

  // Blink med jævne mellemrum
  const blink = () => {
    if (rig) rig.blink();
    scene.classList.add('blink');
    setTimeout(() => scene.classList.remove('blink'), 140);
    setTimeout(blink, 2500 + Math.random() * 3500);
  };
  setTimeout(blink, 1500);

  // iOS afspiller kun lyd, der er startet af et tryk. Vi "låser op" med et stumt klip ved første tryk.
  const stumWav = () => {
    const n = 800, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const w = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
    w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 16000, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  };
  const laasLydOp = () => {
    if (lydLaastOp) return;
    lydLaastOp = true;
    try { lyd.src = stumWav(); lyd.play().catch(() => {}); } catch (e) { /* ignorer */ }
    if ('speechSynthesis' in window) { try { speechSynthesis.getVoices(); } catch (e) { /* ignorer */ } }
  };

  // ---------- Lip-sync ----------
  const viseme = c => {
    c = (c || '').toLowerCase();
    if ('aeæ'.includes(c)) return 'open';
    if ('iy'.includes(c)) return 'mid';
    if ('ouwøå'.includes(c)) return 'round';
    if ('mbp'.includes(c)) return 'closed';
    if (/[a-z]/.test(c)) return 'small';
    return 'closed';
  };
  let animId = null;
  const stopAnim = () => { if (animId) cancelAnimationFrame(animId); animId = null; mund('closed'); };

  const animerFraTider = tale => {
    // ElevenLabs giver start-tidspunkt pr. tegn: find tegnet ved den aktuelle afspilningstid
    const starts = tale.starts || [], chars = tale.chars || [];
    let i = 0;
    const trin = () => {
      const t = lyd.currentTime;
      while (i < starts.length - 1 && starts[i + 1] <= t) i++;
      mund(lyd.paused || lyd.ended ? 'closed' : viseme(chars[i]));
      animId = requestAnimationFrame(trin);
    };
    animId = requestAnimationFrame(trin);
  };
  const animerTilfaeldigt = () => {
    // Uden tidsstempler (browserens egen stemme): skift mundstilling i et taletempo
    const former = ['open', 'mid', 'small', 'round', 'mid', 'open', 'small'];
    let sidst = 0, n = 0;
    const trin = ts => {
      if (ts - sidst > 90 + Math.random() * 70) { mund(former[n++ % former.length]); sidst = ts; }
      animId = requestAnimationFrame(trin);
    };
    animId = requestAnimationFrame(trin);
  };

  // ---------- Afspilning ----------
  const sigMedElevenLabs = tale => new Promise(resolve => {
    afbrydTale = () => { stopAnim(); resolve(); };
    lyd.onended = () => { stopAnim(); resolve(); };
    lyd.onerror = () => { stopAnim(); resolve(); };
    lyd.src = 'data:' + (tale.mime || 'audio/mpeg') + ';base64,' + tale.audio;
    lyd.play().then(() => animerFraTider(tale)).catch(() => { stopAnim(); resolve(); });
  });

  let britiskStemme = null;
  const findStemme = () => {
    if (britiskStemme || !('speechSynthesis' in window)) return britiskStemme;
    const v = speechSynthesis.getVoices();
    britiskStemme = v.find(s => /en[-_]GB/i.test(s.lang) && /female|Kate|Serena|Stephanie|Martha|Libby|Sonia|Google UK English Female/i.test(s.name))
      || v.find(s => /en[-_]GB/i.test(s.lang)) || v.find(s => /^en/i.test(s.lang)) || null;
    return britiskStemme;
  };
  const sigMedBrowser = tekst => new Promise(resolve => {
    if (!('speechSynthesis' in window)) { resolve(); return; }
    afbrydTale = () => { stopAnim(); resolve(); };
    const u = new SpeechSynthesisUtterance(tekst);
    const stemme = findStemme();
    if (stemme) u.voice = stemme;
    u.lang = 'en-GB'; u.rate = 1.02; u.pitch = 1.05;
    u.onend = () => { stopAnim(); resolve(); };
    u.onerror = () => { stopAnim(); resolve(); };
    animerTilfaeldigt();
    speechSynthesis.speak(u);
  });

  const afspilKoe = async () => {
    if (afspiller) return;
    afspiller = true;
    while (koe.length) {
      const s = koe.shift();
      saetTilstand('talking', 'Speaking…');
      if (svarBoble) { svarBoble.textContent += (svarBoble.textContent ? ' ' : '') + s.text; transskript.scrollTop = transskript.scrollHeight; }
      if (s.speech && s.speech.audio) await sigMedElevenLabs(s.speech); else await sigMedBrowser(s.text);
      if (tilstand !== 'talking') { koe = []; break; }   // afbrudt af brugeren
    }
    afspiller = false;
    if (stroemFaerdig && tilstand === 'talking') faerdigMedSvar();
  };

  const faerdigMedSvar = () => {
    if (svarBoble && svarBoble.textContent) historik.push({ role: 'assistant', content: svarBoble.textContent });
    svarBoble = null;
    saetTilstand('idle', 'Tap the microphone to talk');
    if (haandfri.checked) startLytning();
  };

  const stopAlt = () => {
    if (stopSignal) { stopSignal.abort(); stopSignal = null; }
    koe = []; stroemFaerdig = true;
    try { lyd.pause(); } catch (e) { /* ignorer */ }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    stopAnim();
    if (afbrydTale) { const f = afbrydTale; afbrydTale = null; f(); }
    if (svarBoble && svarBoble.textContent) historik.push({ role: 'assistant', content: svarBoble.textContent });
    svarBoble = null;
    afspiller = false;
  };

  // ---------- Samtale ----------
  const send = async tekst => {
    tekst = (tekst || '').trim();
    if (!tekst) return;
    stopLytning();
    historik.push({ role: 'user', content: tekst });
    boble('bruger', tekst);
    svarBoble = boble('avatar', '');
    saetTilstand('thinking', 'Thinking…');
    stroemFaerdig = false; koe = [];
    stopSignal = new AbortController();
    try {
      const r = await fetch('/avatar/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: historik.slice(-24) }), signal: stopSignal.signal,
      });
      if (!r.ok) throw new Error(r.status === 401 ? 'You have been logged out. Reload the page.' : 'Server error ' + r.status);
      const laeser = r.body.getReader(); const dekoder = new TextDecoder(); let buf = '';
      for (;;) {
        const { value, done } = await laeser.read();
        if (done) break;
        buf += dekoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const blok = buf.slice(0, idx); buf = buf.slice(idx + 2);
          let event = 'message', data = '';
          blok.split('\n').forEach(l => { if (l.startsWith('event:')) event = l.slice(6).trim(); else if (l.startsWith('data:')) data += l.slice(5).trim(); });
          if (!data) continue;
          const d = JSON.parse(data);
          if (event === 'sentence') { koe.push(d); if (tilstand !== 'idle') { saetTilstand('talking', 'Speaking…'); afspilKoe(); } }
          else if (event === 'notice') { boble('fejl', d.message); }
          else if (event === 'error') { boble('fejl', d.message); }
        }
      }
      stroemFaerdig = true;
      if (!afspiller) { if (tilstand === 'talking' || tilstand === 'thinking') faerdigMedSvar(); }
    } catch (e) {
      stroemFaerdig = true;
      if (e.name !== 'AbortError') { boble('fejl', e.message || 'Something went wrong.'); }
      if (svarBoble && !svarBoble.textContent) svarBoble.remove();
      svarBoble = null;
      saetTilstand('idle', 'Tap the microphone to talk');
    }
  };

  // ---------- Talegenkendelse ----------
  const Genkendelse = window.SpeechRecognition || window.webkitSpeechRecognition;
  let midlertidig = null;
  const startLytning = () => {
    if (!Genkendelse) { saetTilstand('idle', 'Speech recognition is not available here. Type instead.'); tekstfelt.focus(); return; }
    if (tilstand === 'listening') return;
    stopAlt();
    genkender = new Genkendelse();
    genkender.lang = 'en-GB'; genkender.interimResults = true; genkender.maxAlternatives = 1; genkender.continuous = false;
    let endelig = '';
    genkender.onresult = ev => {
      let del = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) endelig += ev.results[i][0].transcript; else del += ev.results[i][0].transcript;
      }
      const vis = (endelig + ' ' + del).trim();
      if (vis) { if (!midlertidig) midlertidig = boble('bruger midlertidig', ''); midlertidig.textContent = vis; }
    };
    genkender.onerror = ev => {
      if (midlertidig) { midlertidig.remove(); midlertidig = null; }
      const besked = ev.error === 'not-allowed' ? 'Microphone access was denied. Allow it in the browser settings.'
        : ev.error === 'no-speech' ? 'I didn\'t catch that. Tap and try again.' : 'Speech recognition error: ' + ev.error;
      saetTilstand('idle', besked);
    };
    genkender.onend = () => {
      if (midlertidig) { midlertidig.remove(); midlertidig = null; }
      const t = endelig.trim();
      if (t) send(t); else if (tilstand === 'listening') saetTilstand('idle', 'Tap the microphone to talk');
    };
    saetTilstand('listening', 'Listening…');
    try { genkender.start(); } catch (e) { saetTilstand('idle', 'Could not start the microphone.'); }
  };
  const stopLytning = () => { if (genkender) { try { genkender.onend = null; genkender.stop(); } catch (e) { /* ignorer */ } genkender = null; } if (midlertidig) { midlertidig.remove(); midlertidig = null; } };

  // ---------- Knapper ----------
  mic.addEventListener('click', () => {
    laasLydOp();
    if (tilstand === 'listening') { stopLytning(); saetTilstand('idle', 'Tap the microphone to talk'); return; }
    startLytning();
  });
  tekstform.addEventListener('submit', ev => {
    ev.preventDefault(); laasLydOp();
    const t = tekstfelt.value; tekstfelt.value = '';
    if (tilstand === 'talking' || tilstand === 'thinking') { stopAlt(); }
    send(t);
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { stopLytning(); stopAlt(); saetTilstand('idle', 'Tap the microphone to talk'); } });
  if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => { britiskStemme = null; findStemme(); };
})();
