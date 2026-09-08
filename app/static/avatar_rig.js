// Animerer et uploadet portræt som talende hoved: underansigtet (en kopi af billedet klippet i en U-form
// under munden) skubbes ned, mens et mørkt mundhul med tænder tegnes i mellemrummet. Øjnene blinker ved at
// vise huden lige over øjet i øjets område. Alt sker i ét SVG-element med billedets egne koordinater.
window.AvatarRig = function (container, rig, src) {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (navn, attr, parent) => {
    const e = document.createElementNS(NS, navn);
    for (const k in attr) e.setAttribute(k, attr[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const billede = (attr, parent) => {
    const i = el('image', Object.assign({ width: rig.w, height: rig.h, preserveAspectRatio: 'none' }, attr), parent);
    i.setAttributeNS('http://www.w3.org/1999/xlink', 'href', src); i.setAttribute('href', src);
    return i;
  };
  const uid = 'rig' + Math.random().toString(36).slice(2, 8);

  container.innerHTML = '';
  const svg = el('svg', { viewBox: `0 0 ${rig.w} ${rig.h}`, class: 'av-figur rig-figur', 'aria-hidden': 'true' }, container);
  const defs = el('defs', {}, svg);
  const hoved = el('g', { class: 'av-hoved rig-hoved' }, svg);
  billede({}, hoved);

  // --- mund ---
  const m = rig.mund;
  const hx = m.b * 0.75, dybde = m.b * 1.2, sigma = Math.max(2, m.b * 0.07);
  // Kæben: hård kant i mundlinjen (clip), bløde kanter i siderne og under hagen (blurret maske),
  // så den forskudte kopi glider over i det stillestående billede.
  const kaebeClip = el('clipPath', { id: uid + 'k' }, defs);
  el('rect', { x: 0, y: m.y, width: rig.w, height: rig.h - m.y }, kaebeClip);
  const filt = el('filter', { id: uid + 'f', x: '-20%', y: '-20%', width: '140%', height: '140%' }, defs);
  el('feGaussianBlur', { stdDeviation: sigma }, filt);
  const maske = el('mask', { id: uid + 'm', maskUnits: 'userSpaceOnUse', x: 0, y: 0, width: rig.w, height: rig.h }, defs);
  el('rect', { x: 0, y: 0, width: rig.w, height: rig.h, fill: 'black' }, maske);
  const top = m.y - sigma * 3;
  el('path', { fill: 'white', filter: `url(#${uid}f)`, d: `M${m.x - hx} ${top} L${m.x + hx} ${top} L${m.x + hx} ${m.y} C${m.x + hx * 1.35} ${m.y + dybde * 0.45} ${m.x + hx * 0.7} ${m.y + dybde} ${m.x} ${m.y + dybde} C${m.x - hx * 0.7} ${m.y + dybde} ${m.x - hx * 1.35} ${m.y + dybde * 0.45} ${m.x - hx} ${m.y}Z` }, maske);
  const mundHul = el('path', { fill: '#2a0b0e' }, hoved);
  const taender = el('rect', { fill: '#f6f1e8', rx: m.b * 0.04 }, hoved);
  const tunge = el('ellipse', { fill: '#c9605f', opacity: 0 }, hoved);
  const kaebe = el('g', { 'clip-path': `url(#${uid}k)`, mask: `url(#${uid}m)` }, hoved);
  billede({}, kaebe);

  const MAKS_DROP = m.b * 0.26;
  const FORMER = { closed: [0, 1], small: [0.22, 1], mid: [0.5, 1], open: [1, 1], round: [0.75, 0.55] };
  const mund = form => {
    const [andel, bredde] = FORMER[form] || FORMER.closed;
    const drop = MAKS_DROP * andel;
    kaebe.setAttribute('transform', `translate(0 ${drop.toFixed(1)})`);
    if (drop < 0.5) { mundHul.setAttribute('d', ''); taender.setAttribute('height', 0); tunge.setAttribute('opacity', 0); return; }
    const hb = (m.b / 2) * bredde, top = m.y - MAKS_DROP * 0.05;
    // mundhul: let buet overlæbe-kant øverst, dyb bue nederst (dækkes delvist af kæben)
    mundHul.setAttribute('d', `M${m.x - hb} ${top} Q${m.x} ${top - drop * 0.25} ${m.x + hb} ${top} Q${m.x} ${m.y + drop * 1.9} ${m.x - hb} ${top}Z`);
    const th = Math.min(drop * 0.45, m.b * 0.09);
    taender.setAttribute('x', m.x - hb * 0.8); taender.setAttribute('y', top); taender.setAttribute('width', hb * 1.6); taender.setAttribute('height', th);
    tunge.setAttribute('cx', m.x); tunge.setAttribute('cy', m.y + drop * 0.95); tunge.setAttribute('rx', hb * 0.7); tunge.setAttribute('ry', drop * 0.35);
    tunge.setAttribute('opacity', andel > 0.6 ? 0.9 : 0);
  };

  // --- øjne (blink) ---
  const laag = [];
  if (rig.oejne && rig.blink !== false) {
    for (const side of ['v', 'h']) {
      const o = rig.oejne[side]; if (!o) continue;
      const cp = el('clipPath', { id: uid + side }, defs);
      el('ellipse', { cx: o.x, cy: o.y, rx: o.b / 2, ry: o.b * 0.36 }, cp);
      const g = el('g', { 'clip-path': `url(#${uid}${side})` }, hoved);
      const img = billede({}, g);
      img.setAttribute('transform', 'translate(0 0)');
      img.style.visibility = 'hidden';
      laag.push({ img, dy: o.b * 0.62 });
    }
  }
  let blinker = false;
  const blink = () => {
    if (!laag.length || blinker) return;
    blinker = true;
    laag.forEach(l => { l.img.setAttribute('transform', `translate(0 ${l.dy.toFixed(1)})`); l.img.style.visibility = 'visible'; });
    setTimeout(() => { laag.forEach(l => { l.img.style.visibility = 'hidden'; }); blinker = false; }, 130);
  };

  // --- markører til kalibrering (bruges kun på indstillingssiden) ---
  const markoerer = el('g', { class: 'rig-markoerer', style: 'display:none' }, svg);
  const visMarkoerer = vis => { markoerer.style.display = vis ? '' : 'none'; if (!vis) return;
    markoerer.innerHTML = '';
    const sw = Math.max(2, rig.w / 400);
    el('line', { x1: m.x - m.b / 2, y1: m.y, x2: m.x + m.b / 2, y2: m.y, stroke: '#ff3b30', 'stroke-width': sw * 1.5 }, markoerer);
    el('circle', { cx: m.x, cy: m.y, r: sw * 3, fill: '#ff3b30' }, markoerer);
    if (rig.oejne) for (const side of ['v', 'h']) { const o = rig.oejne[side]; if (o) el('ellipse', { cx: o.x, cy: o.y, rx: o.b / 2, ry: o.b * 0.36, fill: 'none', stroke: '#0a84ff', 'stroke-width': sw }, markoerer); }
  };

  const tilBilledKoordinat = ev => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return { x: Math.round(p.x), y: Math.round(p.y) };
  };

  mund('closed');
  return { svg, rig, mund, blink, visMarkoerer, tilBilledKoordinat, harBlink: laag.length > 0 };
};
