// Opdaterer bilagssiden automatisk mens aflæsningen kører
document.querySelectorAll('[data-poll]').forEach(el => {
  const url = el.dataset.poll;
  const tjek = () => fetch(url).then(r => r.json()).then(d => {
    if (d.status !== 'aflaeser' && d.status !== 'uploadet') location.reload(); else setTimeout(tjek, 2500);
  }).catch(() => setTimeout(tjek, 5000));
  setTimeout(tjek, 2500);
});

// Foreslår momskode når kontoen ændres
const kontoValg = document.querySelector('select[name=konto]');
if (kontoValg) kontoValg.addEventListener('change', () => {
  const m = kontoValg.selectedOptions[0]?.dataset.moms;
  const momsValg = document.querySelector('select[name=momskode]');
  if (m && momsValg) momsValg.value = m;
});

// Sum af debet/kredit i manuel postering
const tilTal = s => { s = (s || '').trim().replace(/\./g, '').replace(',', '.'); const n = parseFloat(s); return isNaN(n) ? 0 : n; };
const format = n => n.toLocaleString('da-DK', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const linjer = document.querySelector('table.linjer');
if (linjer) {
  const opdater = () => {
    let d = 0, k = 0;
    linjer.querySelectorAll('input[name^=debet_]').forEach(i => d += tilTal(i.value));
    linjer.querySelectorAll('input[name^=kredit_]').forEach(i => k += tilTal(i.value));
    document.getElementById('sum-debet').textContent = format(d);
    document.getElementById('sum-kredit').textContent = format(k);
    const diff = document.getElementById('difference');
    diff.textContent = Math.abs(d - k) > 0.004 ? 'Difference: ' + format(d - k) : 'Balancerer';
    diff.style.color = Math.abs(d - k) > 0.004 ? '#b3261e' : '#1e7a3a';
  };
  linjer.addEventListener('input', opdater); opdater();
}

// Låste formularer (bogførte bilag) kan ikke redigeres
document.querySelectorAll('form[data-laast]').forEach(f => f.querySelectorAll('input,select,textarea,button').forEach(e => e.disabled = true));
