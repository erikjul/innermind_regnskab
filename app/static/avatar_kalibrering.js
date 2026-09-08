// Kalibrering af det uploadede portræt: klik i billedet for at placere mund og øjne, se bevægelsen, gem.
(() => {
  const boks = document.getElementById('kalibrering');
  if (!boks || !window.AvatarRig) return;
  const rig = JSON.parse(boks.dataset.rig);
  const preview = document.getElementById('rigpreview');
  const status = document.getElementById('rigstatus');
  const mundb = document.getElementById('mundb'), oejeb = document.getElementById('oejeb'), blinkBoks = document.getElementById('blink');
  let r = null;

  const byg = () => {
    rig.blink = blinkBoks.checked;
    r = window.AvatarRig(preview, JSON.parse(JSON.stringify(rig)), boks.dataset.portraet);
    r.visMarkoerer(true);
    r.svg.addEventListener('click', ev => {
      const p = r.tilBilledKoordinat(ev);
      const del = boks.querySelector('input[name=del]:checked').value;
      if (del === 'mund') { rig.mund.x = p.x; rig.mund.y = p.y; }
      else { rig.oejne[del].x = p.x; rig.oejne[del].y = p.y; }
      byg();
    });
  };
  mundb.addEventListener('input', () => { rig.mund.b = +mundb.value; byg(); });
  oejeb.addEventListener('input', () => { rig.oejne.v.b = rig.oejne.h.b = +oejeb.value; byg(); });
  blinkBoks.addEventListener('change', byg);

  document.getElementById('proev').addEventListener('click', () => {
    r.visMarkoerer(false);
    const former = ['small', 'open', 'mid', 'round', 'open', 'small', 'mid', 'open', 'closed', 'small', 'open', 'round', 'mid', 'closed'];
    let i = 0;
    const t = setInterval(() => { r.mund(former[i++ % former.length]); if (i === 4) r.blink(); if (i > 24) { clearInterval(t); r.mund('closed'); r.visMarkoerer(true); } }, 110);
  });
  document.getElementById('gemrig').addEventListener('click', async () => {
    status.textContent = 'Gemmer…';
    const svar = await fetch('/avatar/portraet/kalibrering', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rig) });
    const d = await svar.json().catch(() => ({}));
    status.textContent = svar.ok ? 'Gemt. Åbn avataren for at prøve.' : ('Fejl: ' + (d.fejl || svar.status));
  });
  byg();
})();
