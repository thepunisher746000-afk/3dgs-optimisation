// Portail 3DGS : application monopage sans framework. Pages : accueil, modèles, optimiser,
// résultats, visualiseur, documentation. Parle au serveur app.py via /api/*.
'use strict';

const S = { api: false, models: [], jobs: [], docs: [], configs: [], currentJob: null, poll: null,
            form: { tool: 'clean', params: {} } };
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const page = $('#page');

// ------------------------------------------------------------------ utilitaires
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (n, d = 0) => (n == null || Number.isNaN(n) ? '—' : Number(n).toLocaleString('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: d }));
function size(b) {
  if (b == null) return '—';
  const u = ['o', 'Ko', 'Mo', 'Go']; let i = 0;
  while (b >= 1024 && i < 3) { b /= 1024; i++; }
  return `${nf(b, i ? 1 : 0)} ${u[i]}`;
}
function ago(t) {
  const s = Date.now() / 1000 - t;
  if (s < 60) return 'à l’instant';
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return new Date(t * 1000).toLocaleDateString('fr-FR');
}
function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), ms);
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts.body && !(opts.body instanceof Blob) && typeof opts.body !== 'string'
    ? { ...opts, method: opts.method || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts.body) }
    : opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Erreur ${r.status}`);
  return data;
}
const copy = (txt) => navigator.clipboard.writeText(txt).then(() => toast('Copié dans le presse-papiers'));
const viewerUrl = (paths) => '/viewer/?models=' + paths.map((p) => '/' + p).join(',');
const viewable = (p) => /\.(ply|splat|ksplat|spz)$/i.test(p);
const viewPath = (p) => (p.endsWith('.gsq') ? p + '.ply' : p);

const ICON = {
  analyze: '<path d="M21 21l-4.3-4.3"/><circle cx="11" cy="11" r="7"/>',
  clean: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
  prune: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/>',
  sh: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18"/>',
  gsq: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
  pipeline: '<path d="M3 3v18h18"/><path d="M7 15v3M12 10v8M17 6v12"/>',
  synthetic: '<path d="M12 2l3 7h7l-5.5 4.5 2 7.5L12 17l-6.5 4 2-7.5L2 9h7z"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
  next: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  ext: '<path d="M14 3h7v7M10 14L21 3M21 14v7H3V3h7"/>',
};
const icon = (k, sz = 16) => `<svg viewBox="0 0 24 24" width="${sz}" height="${sz}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</svg>`;

// ------------------------------------------------------------------ outils
const TOOLS = {
  analyze: {
    title: 'Analyser', short: 'Diagnostic', next: 'clean',
    what: 'Mesure le profil du modèle : nombre de gaussiennes, poids des harmoniques sphériques, distributions d’opacité et de taille, et combien de gaussiennes chaque filtre de nettoyage supprimerait.',
    when: 'Toujours en premier : c’est la photo « avant » du rapport, et elle aide à régler le nettoyage.',
    doc: 'docs/02_capture_generation.md', fields: [],
  },
  clean: {
    title: 'Nettoyer', short: 'Floaters, halo, invisibles', next: 'prune',
    what: 'Supprime les gaussiennes invalides, invisibles (opacité ≈ 0), géantes, les « floaters » (à la fois transparents et gros) et le halo de points lointains.',
    when: 'Juste après la génération. Le niveau « Moyen » est sans perte visible dans nos tests et c’est l’étape qui améliore le plus la fluidité.',
    doc: 'docs/03_optimisation.md',
    fields: [
      { k: 'preset', type: 'choice', label: 'Niveau de nettoyage', def: 'medium', options: [
        ['light', 'Léger', 'Seulement l’invisible (opacité < 1/255). Sans risque.'],
        ['medium', 'Moyen — recommandé', '+ géantes, floaters, halo lointain, points isolés.'],
        ['aggressive', 'Agressif', '+ filtre statistique (scipy), recadrage serré. À vérifier à l’œil.'],
        ['custom', 'Personnalisé', 'Uniquement les filtres choisis dans « Réglages avancés ».']] },
      { k: 'min_opacity', type: 'number', label: 'Opacité minimale', placeholder: 'ex. 0.004', adv: true, step: 0.001,
        help: 'Gaussiennes plus transparentes que ce seuil supprimées. 0.004 ≈ 1/255 (invisible).' },
      { k: 'floaters', type: 'check', label: 'Filtre floaters (transparentes ET grosses)', adv: true },
      { k: 'floater_alpha', type: 'number', label: 'Floaters : opacité max.', def: 0.2, step: 0.05, adv: true, show: (p) => p.floaters },
      { k: 'floater_mult', type: 'number', label: 'Floaters : taille min. (× médiane)', def: 5, adv: true, show: (p) => p.floaters },
      { k: 'max_scale_mult', type: 'number', label: 'Taille max. (× médiane)', placeholder: 'ex. 30', adv: true,
        help: 'Supprime les gaussiennes géantes. Attention au ciel ou aux murs uniformes.' },
      { k: 'auto_crop', type: 'check', label: 'Recadrage automatique (retire le halo lointain)', adv: true },
      { k: 'sor', type: 'check', label: 'Filtre statistique SOR (nécessite scipy)', adv: true },
    ],
  },
  prune: {
    title: 'Élaguer', short: 'Garder l’essentiel', next: 'gsq',
    what: 'Classe les gaussiennes par importance (contribution à l’image) et ne garde que les plus utiles. Moins de gaussiennes = fichier plus léger et affichage plus fluide.',
    when: 'Après le nettoyage. Commencer à 75 % et descendre tant que la qualité reste bonne dans le visualiseur : le bon taux dépend de chaque scène.',
    doc: 'docs/03_optimisation.md',
    fields: [
      { k: 'keep_ratio', type: 'range', label: 'Part des gaussiennes conservée', def: 0.75, min: 0.1, max: 1, step: 0.05,
        fmt: (v) => `${Math.round(v * 100)} %`, help: 'En dessous de 50 %, des trous peuvent apparaître sur les surfaces peu texturées.' },
      { k: 'score', type: 'choice', label: 'Méthode de classement', def: 'orbit', options: [
        ['orbit', 'Vues virtuelles — recommandé', 'Caméras en orbite autour de la scène, tient compte de ce qui est caché.'],
        ['cameras', 'Poses de capture', 'Le plus fidèle : utilise les vraies caméras (COLMAP ou cameras.json).'],
        ['proxy', 'Rapide', 'Opacité × taille, sans caméra. Ne voit pas les gaussiennes cachées.']] },
      { k: 'cameras', type: 'text', label: 'Dossier ou fichier des caméras', placeholder: 'data/sceneA/sparse/0  ou  data/sceneA/cameras.json',
        show: (p) => p.score === 'cameras' },
      { k: 'occlusion', type: 'check', label: 'Tenir compte des occultations (recommandé)', def: true, show: (p) => p.score !== 'proxy' },
      { k: 'compensate', type: 'check', label: 'Compenser (recommandé) : les voisines reprennent l’opacité et la couleur des gaussiennes supprimées', def: true,
        help: 'Évite l’aspect « tacheté » / troué des élagages forts. Nécessite scipy.' },
      { k: 'min_coverage', type: 'number', label: 'Anti-trous : part minimale gardée par zone', def: 0.25, step: 0.05, adv: true,
        help: 'Chaque zone visible garde au moins cette fraction de ses gaussiennes : l’élagage est réparti au lieu de vider des plaques. 0 = désactivé.' },
      { k: 'orbit_n', type: 'number', label: 'Nombre de caméras virtuelles', def: 32, adv: true, show: (p) => p.score === 'orbit' },
    ],
  },
  sh: {
    title: 'Couleurs (SH)', short: 'Reflets ↔ poids', next: 'gsq',
    what: 'Réduit les harmoniques sphériques, qui codent les reflets selon le point de vue et pèsent 76 % du fichier.',
    when: 'Scène mate : degré 0 ou 1 suffit. Objets brillants (métal, vitres, sol ciré) : garder 2 ou 3.',
    doc: 'docs/03_optimisation.md',
    fields: [
      { k: 'degree', type: 'choice', label: 'Degré conservé', def: '1', options: [
        ['0', 'Degré 0', 'Couleur fixe. ÷ 4,2 en taille.'], ['1', 'Degré 1', 'Reflets doux. ÷ 2,6.'],
        ['2', 'Degré 2', 'Max. du visualiseur web. ÷ 1,6.'], ['3', 'Degré 3', 'Complet (aucune réduction).']] },
      { k: 'adaptive', type: 'number', label: 'SH adaptatifs : seuil', placeholder: 'ex. 0.05', adv: true, step: 0.01,
        help: 'Met à zéro les reflets des gaussiennes quasi mates. Gain visible après compression.' },
    ],
  },
  gsq: {
    title: 'Compresser', short: 'Quantification', next: null,
    what: 'Encode le modèle sur moins de bits (positions 16 bits, rotation 32 bits, couleurs 8 bits, dictionnaire pour les reflets) puis compresse : ×10 à ×16 sans perte visible. Produit aussi une version décodée pour la vérifier dans le visualiseur.',
    when: 'En dernier, sur le modèle nettoyé et élagué.',
    doc: 'docs/03_optimisation.md',
    fields: [
      { k: 'sh', type: 'choice', label: 'Codage des reflets (SH)', def: 'vq', options: [
        ['vq', 'Dictionnaire — recommandé', 'k-means : 2 octets par gaussienne. Le plus compact.'],
        ['8bit', '8 bits', 'Plus fidèle, plus lourd.'], ['none', 'Supprimer', 'Couleur fixe uniquement.']] },
      { k: 'codebook', type: 'number', label: 'Taille du dictionnaire', def: 4096, adv: true, show: (p) => p.sh === 'vq',
        help: '4096 pour > 500 000 gaussiennes ; réduire (1024) sur une petite scène.' },
      { k: 'sh_zero', type: 'number', label: 'SH adaptatifs : seuil', placeholder: 'ex. 0.05', adv: true, step: 0.01, show: (p) => p.sh === 'vq' },
      { k: 'pos', type: 'select', label: 'Précision des positions', def: '16', adv: true,
        options: [['16', '16 bits par axe'], ['11-10-11', '11-10-11 bits (plus compact)']] },
    ],
  },
  pipeline: {
    title: 'Tout comparer', short: 'Toutes les configurations', next: null,
    what: 'Applique d’un coup une série de configurations (original, nettoyages, élagages, SH, compression) et produit un tableau comparatif dans « Résultats ».',
    when: 'Pour le rapport : mêmes réglages sur chaque scène, puis comparaison visuelle dans le visualiseur.',
    doc: 'docs/04_integration_mesures.md',
    fields: [
      { k: 'config', type: 'configs', label: 'Jeu de configurations', def: 'configs/default.json' },
      { k: 'gzip', type: 'check', label: 'Mesurer aussi la taille après compression HTTP (gzip)', def: true },
    ],
  },
  synthetic: {
    title: 'Scène de test', short: 'Pour essayer', next: 'pipeline', noInput: true,
    what: 'Génère une scène artificielle avec des défauts connus (floaters, halo, gaussiennes cachées…) pour tester la chaîne sans capture réelle.',
    when: 'Pour découvrir les outils ou vérifier qu’une modification du code ne casse rien.',
    doc: 'docs/04_integration_mesures.md',
    fields: [{ k: 'n', type: 'number', label: 'Nombre de gaussiennes', def: 200000, step: 10000 }],
  },
};

// ------------------------------------------------------------------ routeur
const ROUTES = { accueil: pageHome, modeles: pageModels, optimiser: pageOptimize, benchmark: pageBenchmark,
                 resultats: pageResults, visualiseur: pageViewer, docs: pageDocs };
function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, query] = h.split('?');
  const [name, ...rest] = path.split('/');
  return { name: ROUTES[name] ? name : 'accueil', rest: rest.join('/'), q: new URLSearchParams(query || '') };
}
async function route() {
  const r = parseHash();
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === r.name));
  if (S.poll && r.name !== 'optimiser') { clearInterval(S.poll); S.poll = null; }
  window.scrollTo(0, 0);
  try { await ROUTES[r.name](r); } catch (e) { page.innerHTML = `<div class="card empty">Erreur : ${esc(e.message)}</div>`; console.error(e); }
}
const go = (hash) => { location.hash = hash; };
window.addEventListener('hashchange', route);

function needApi() {
  return `<div class="notice"><b>Mode lecture seule.</b> Pour importer des modèles et lancer les outils, démarrez le portail avec
    <code>python3 app.py</code> depuis le dossier du projet, puis ouvrez <code>http://localhost:8000</code>.</div>`;
}

// ------------------------------------------------------------------ accueil
async function pageHome() {
  let models = [], results = [], jobs = [];
  if (S.api) [models, results, jobs] = await Promise.all([api('/api/models'), api('/api/results'), api('/api/jobs')]);
  const running = jobs.filter((j) => j.status === 'running').length;
  page.innerHTML = `
    ${S.api ? '' : needApi()}
    <div class="card hero">
      <h1>Rendre les modèles 3D Gaussian Splatting légers et fluides</h1>
      <p>Importez un modèle 3DGS (.ply exporté par PostShot, Polycam, Luma, Brush…), nettoyez-le, allégez-le,
        compressez-le, puis mesurez l’effet sur la taille, la fluidité et la qualité visuelle.</p>
      <div class="row">
        <a class="btn primary lg" href="#/modeles">${icon('upload')} Importer un modèle</a>
        <button class="btn lg" id="quick" ${S.api ? '' : 'disabled'}>${icon('play')} Essai rapide sur une scène de test</button>
        <a class="btn lg" href="#/docs/README.md">Lire la présentation</a>
      </div>
    </div>

    <h2 style="margin:26px 0 12px">Le parcours en 4 étapes</h2>
    <div class="grid g4 steps">
      <div class="card step"><h3>Importer</h3><p>Glissez le fichier .ply du modèle généré. Il apparaît dans la liste des modèles.</p>
        <a class="btn" href="#/modeles">Modèles ${icon('next')}</a></div>
      <div class="card step"><h3>Analyser et nettoyer</h3><p>Diagnostic du modèle puis suppression des floaters et du halo, sans perte visible.</p>
        <a class="btn" href="#/optimiser?tool=analyze">Analyser ${icon('next')}</a></div>
      <div class="card step"><h3>Alléger et compresser</h3><p>Élagage des gaussiennes peu utiles, réduction des reflets, quantification.</p>
        <a class="btn" href="#/optimiser?tool=prune">Optimiser ${icon('next')}</a></div>
      <div class="card step"><h3>Mesurer</h3><p>Comparer les versions dans le navigateur : chargement, FPS, PSNR/SSIM.</p>
        <a class="btn" href="#/resultats">Résultats ${icon('next')}</a></div>
    </div>

    <div class="grid g3" style="margin-top:16px">
      <div class="card stat"><div class="v">${S.api ? models.length : '—'}</div><div class="l">modèles disponibles</div></div>
      <div class="card stat"><div class="v">${S.api ? results.length : '—'}</div><div class="l">scènes avec résultats</div></div>
      <div class="card stat"><div class="v">${S.api ? running : '—'}</div><div class="l">tâches en cours</div></div>
    </div>

    ${jobs.length ? `<div class="card" style="margin-top:16px"><h2>Dernières tâches</h2>${jobsTable(jobs.slice(0, 6))}</div>` : ''}`;
  $('#quick')?.addEventListener('click', quickStart);
  bindJobRows();
}

function jobsTable(jobs) {
  return `<div class="table-wrap"><table><thead><tr><th>Tâche</th><th>Entrée</th><th>État</th><th class="num">Durée</th><th></th></tr></thead><tbody>
    ${jobs.map((j) => `<tr class="job-row" data-id="${j.id}" style="cursor:pointer"><td><b>${esc(j.title)}</b></td>
      <td class="muted">${esc(j.input || '—')}</td><td>${statusBadge(j.status)}</td>
      <td class="num">${nf(((j.end || Date.now() / 1000) - j.start), 1)} s</td><td class="num">${icon('next')}</td></tr>`).join('')}
  </tbody></table></div>`;
}
function bindJobRows() {
  $$('.job-row').forEach((tr) => tr.addEventListener('click', () => go(`#/optimiser?job=${tr.dataset.id}`)));
}
const statusBadge = (s) => ({ running: '<span class="badge run">en cours…</span>', done: '<span class="badge ok">terminé</span>',
  error: '<span class="badge err">erreur</span>' }[s] || s);

async function quickStart() {
  toast('Génération de la scène de test…');
  const j = await api('/api/run', { body: { tool: 'synthetic', params: { n: 200000 } } });
  S.chain = { after: j.id, tool: 'pipeline', params: { input: 'data/synthetic.ply', config: 'configs/default.json', gzip: true } };
  go(`#/optimiser?job=${j.id}`);
}

// ------------------------------------------------------------------ modèles et captures
const UPLOAD_ACCEPT = '.ply,.splat,.ksplat,.spz,.sog,.gsq,.mp4,.mov,.m4v,.avi,.mkv,.webm,.jpg,.jpeg,.png,.heic,.heif,.tif,.tiff,.webp,.zip';
const dur = (s) => (s == null ? '' : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);

async function pageModels() {
  if (!S.api) { page.innerHTML = `<div class="page-head"><div><h1>Modèles</h1></div></div>${needApi()}`; return; }
  [S.models, S.captures, S.tools] = await Promise.all([api('/api/models'), api('/api/captures'), api('/api/tools')]);
  page.innerHTML = `
    <div class="page-head"><div><h1>Modèles et captures</h1><div class="muted">Importez un modèle 3DGS déjà généré, ou la
      matière première d’une capture (vidéo, photos) : le type est détecté automatiquement.</div></div></div>
    <label class="drop" id="drop">
      <input type="file" id="file" accept="${UPLOAD_ACCEPT}" multiple hidden>
      <strong>${icon('upload', 20)} Glissez des fichiers ici ou cliquez pour choisir</strong>
      <span class="muted">Modèles : .ply, .splat, .ksplat, .spz, .sog · Vidéos : .mp4, .mov, .avi, .mkv, .webm ·
        Photos : .jpg, .png, .heic, .tif ou un .zip de photos</span>
      <div class="progress" id="prog" hidden><div></div></div>
      <div class="small muted" id="prog-label"></div>
    </label>
    <div class="card" style="margin-top:16px" id="captures"></div>
    <div class="card">
      <div class="row" style="margin-bottom:10px"><h2 style="margin:0">Modèles 3DGS (${S.models.length})</h2><span class="spacer"></span>
        <input type="text" class="search" id="filter" placeholder="Filtrer par nom ou dossier…"></div>
      <div id="model-table"></div>
    </div>`;
  renderCaptures();
  renderModelTable('');
  $('#filter').addEventListener('input', (e) => renderModelTable(e.target.value.toLowerCase()));
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => uploadFiles(e.dataTransfer.files));
  $('#file').addEventListener('change', (e) => uploadFiles(e.target.files));
}

function renderCaptures() {
  const el = $('#captures');
  const t = S.tools || {};
  const caps = S.captures || [];
  el.innerHTML = `<h2>Captures (${caps.length})</h2>
    <div class="muted small" style="margin-bottom:12px">Chemin : vidéo → images nettes → modèle 3DGS → optimisation.
      Outils détectés : extraction d’images ${t.opencv ? '<span class="badge ok">OpenCV</span>' : '<span class="badge err">OpenCV absent</span>'}
      · entraînement ${t.trainers?.length ? t.trainers.map((x) => `<span class="badge ok">${esc(x)}</span>`).join(' ')
        : '<span class="badge warn">aucun outil local</span>'}</div>
    ${caps.length ? caps.map((c) => `<div class="capture">
      <div class="row"><b>${esc(c.name)}</b>${c.model ? '<span class="badge ok">modèle généré</span>' : ''}
        <span class="spacer"></span><button class="btn ghost danger" data-delcap="${esc(c.dir)}" title="Supprimer la capture">${icon('trash')}</button></div>
      ${c.videos.map((v) => `<div class="small muted">${icon('play')} ${esc(v.name)} — ${size(v.size)}${v.duration_s ? ` · ${dur(v.duration_s)}` : ''}
        ${v.width ? ` · ${v.width}×${v.height}` : ''}${v.fps ? ` · ${v.fps} im/s` : ''}${v.readable === false ? ' · <span class="badge err">illisible par OpenCV</span>' : ''}</div>`).join('')}
      <div class="small muted">${c.images} image${c.images > 1 ? 's' : ''} dans <code>${esc(c.dir)}/images</code>
        ${c.images && c.images < 50 ? ' <span class="badge warn">peu d’images : viser 100 à 300</span>' : ''}</div>
      ${c.image_sample.length ? `<div class="thumbs-row">${c.image_sample.map((p) => `<img src="/${esc(p)}" loading="lazy">`).join('')}</div>` : ''}
      ${c.check ? `<div class="check-box ${esc(c.check.level)}">
        <b>${{ ok: '✓ Capture exploitable', attention: '⚠ Capture limite', critique: '✕ Capture insuffisante' }[c.check.level] || ''}</b>
        — ${esc(c.check.verdict)}
        <span class="muted small">(${c.check.images} images, ${c.check.linked_pairs} paires liées, ${c.check.components.length} groupe${c.check.components.length > 1 ? 's' : ''})</span>
        ${c.check.issues.length ? `<ul>${c.check.issues.map((i) => `<li>${esc(i.text)}</li>`).join('')}</ul>` : ''}
        ${c.check.advice.length ? `<div class="small"><b>À faire :</b><ul>${c.check.advice.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>` : ''}
      </div>` : ''}
      <div class="row" style="margin-top:8px">
        ${c.images ? `<button class="btn ${c.check ? '' : 'primary'}" data-check="${esc(c.dir)}">${icon('analyze')} ${c.check ? 'Revérifier' : 'Vérifier la capture'}</button>` : ''}
        ${c.videos.length ? `<button class="btn ${c.images ? '' : 'primary'}" data-frames="${esc(c.dir)}" data-video="${esc(c.videos[0].path)}" ${t.opencv ? '' : 'disabled'}>
          ${icon('next')} Extraire les images${c.images ? ' (à nouveau)' : ''}</button>` : ''}
        ${c.images ? `<button class="btn ${c.model || !c.check || c.check.level === 'critique' ? '' : 'primary'}" data-train="${esc(c.dir)}">${icon('play')} Générer le modèle 3DGS</button>
          <button class="btn" data-zip="${esc(c.dir)}">Archive ZIP des photos</button>` : ''}
        ${c.zip ? `<a class="btn ghost" href="/${esc(c.zip)}" download>Télécharger le ZIP</a>` : ''}
        ${c.model ? `<a class="btn primary" href="#/optimiser?tool=analyze&input=${encodeURIComponent(c.model)}">Analyser le modèle ${icon('next')}</a>` : ''}
      </div>
      ${c.images && !t.trainers?.length && !c.model ? `<div class="help small muted" style="margin-top:6px">Aucun outil d’entraînement local :
        « Générer » affichera la marche à suivre (PostShot avec ces images ou la vidéo, Polycam avec l’archive ZIP, Brush…),
        puis importez le .ply obtenu ici.</div>` : ''}
    </div>`).join('') : '<div class="empty" style="padding:14px">Aucune capture. Glissez une vidéo ou des photos ci-dessus.</div>'}`;
  const runJob = async (tool, params) => {
    try { const j = await api('/api/run', { body: { tool, params } }); toast(`${j.title} lancé`); go(`#/optimiser?job=${j.id}`); }
    catch (e) { toast('Erreur : ' + e.message, 5000); }
  };
  $$('[data-frames]', el).forEach((b) => b.addEventListener('click', () => {
    const fps = prompt('Images à garder par seconde de vidéo (2 à 3 pour une marche lente) :', '3');
    if (fps) runJob('frames', { capture: b.dataset.frames, video: b.dataset.video, fps, max_side: 1920 });
  }));
  $$('[data-check]', el).forEach((b) => b.addEventListener('click', () => runJob('check', { capture: b.dataset.check })));
  $$('[data-train]', el).forEach((b) => b.addEventListener('click', () => {
    const c = caps.find((x) => x.dir === b.dataset.train);
    if (c?.check?.level === 'critique' && !confirm('La vérification juge cette capture insuffisante : le modèle sera très incomplet. Lancer quand même ?')) return;
    runJob('train', { capture: b.dataset.train, iterations: 7000 });
  }));
  $$('[data-zip]', el).forEach((b) => b.addEventListener('click', () => runJob('zip', { capture: b.dataset.zip })));
  $$('[data-delcap]', el).forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(`Supprimer définitivement la capture ${b.dataset.delcap} (vidéo, images et fichiers de travail) ?`)) return;
    await api('/api/delete_capture', { body: { path: b.dataset.delcap } });
    toast('Capture supprimée'); pageModels();
  }));
}

function renderModelTable(filter) {
  const rows = S.models.filter((m) => !filter || m.path.toLowerCase().includes(filter));
  if (!rows.length) {
    $('#model-table').innerHTML = `<div class="empty">Aucun modèle${filter ? ' correspondant' : ''}. Importez un .ply ou lancez
      <a href="#/optimiser?tool=synthetic">la scène de test</a>.</div>`;
    return;
  }
  const maxSize = Math.max(...rows.map((m) => m.size));
  $('#model-table').innerHTML = `<div class="table-wrap"><table><thead><tr><th>Nom</th><th>Type détecté</th><th>Dossier</th>
    <th class="num">Gaussiennes</th><th class="num">Taille</th><th class="bar-cell"></th><th>Modifié</th><th class="num">Actions</th></tr></thead><tbody>
    ${rows.map((m) => `<tr>
      <td><b>${esc(m.name)}</b></td>
      <td><span class="badge ${m.usable ? '' : m.category === 'model' ? 'warn' : 'err'}">${esc(m.kind)}</span></td>
      <td class="muted small">${esc(m.dir)}</td>
      <td class="num">${nf(m.count)}</td><td class="num">${size(m.size)}</td>
      <td class="bar-cell"><div class="bar" style="width:${Math.max(2, (100 * m.size) / maxSize)}%"></div></td>
      <td class="muted small">${ago(m.mtime)}</td>
      <td class="num" style="white-space:nowrap">
        ${m.usable ? `<a class="btn ghost" title="Optimiser" href="#/optimiser?tool=${m.dir.startsWith('data') ? 'analyze' : 'clean'}&input=${encodeURIComponent(m.path)}">${icon('next')} Optimiser</a>`
          : m.type === 'gaussians_compressed' || m.type === 'sog' || m.type === 'spz' || m.type === 'ksplat'
            ? `<button class="btn ghost" data-convert="${esc(m.path)}" ${S.tools?.splat_transform ? '' : 'disabled title="nécessite splat-transform (npm install -g @playcanvas/splat-transform)"'}>Convertir en PLY</button>`
            : '<span class="muted small">non exploitable</span>'}
        ${m.viewable || m.name.endsWith('.gsq') ? `<a class="btn ghost" title="Voir dans le visualiseur" href="#/visualiseur?models=${encodeURIComponent(viewPath(m.path))}">${icon('eye')}</a>` : ''}
        <button class="btn ghost danger" title="Supprimer" data-del="${esc(m.path)}">${icon('trash')}</button>
      </td></tr>`).join('')}</tbody></table></div>`;
  $$('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(`Supprimer définitivement ${b.dataset.del} ?`)) return;
    await api('/api/delete', { body: { path: b.dataset.del } });
    toast('Fichier supprimé'); pageModels();
  }));
  $$('[data-convert]').forEach((b) => b.addEventListener('click', async () => {
    const j = await api('/api/run', { body: { tool: 'convert', params: { input: b.dataset.convert } } });
    go(`#/optimiser?job=${j.id}`);
  }));
}

const NEXT_STEP = {
  model: 'Modèle 3DGS prêt : cliquez sur « Optimiser » dans la liste.',
  capture: 'Capture ajoutée : extrayez les images puis générez le modèle (section Captures).',
};

async function uploadFiles(files) {
  const prog = $('#prog');
  const list = [...files];
  const imgs = list.filter((f) => /\.(jpe?g|png|heic|heif|tiff?|webp)$/i.test(f.name));
  let group = null;
  if (imgs.length) {
    group = prompt(`${imgs.length} photo(s) : nom de la capture (un dossier par lieu ou objet) :`,
      `photos_${new Date().toISOString().slice(0, 10)}`);
    if (!group) return;
  }
  const done = [];
  for (const [i, f] of list.entries()) {
    prog.hidden = false;
    $('#prog-label').textContent = `${i + 1}/${list.length} · ${f.name}`;
    await new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', `/api/upload?name=${encodeURIComponent(f.name)}${group ? `&group=${encodeURIComponent(group)}` : ''}`);
      x.upload.onprogress = (e) => { prog.firstElementChild.style.width = `${(100 * e.loaded) / e.total}%`; };
      x.onload = () => (x.status < 300 ? resolve(JSON.parse(x.responseText)) : reject(new Error(JSON.parse(x.responseText).error)));
      x.onerror = () => reject(new Error('échec de l’envoi'));
      x.send(f);
    }).then((r) => done.push(r)).catch((e) => toast(`${f.name} : ${e.message}`, 7000));
  }
  if (done.length) {
    const d = done[done.length - 1].detected;
    const extra = d.kind === 'video' && d.details.duration_s ? ` (${dur(d.details.duration_s)}, ${d.details.width}×${d.details.height})`
      : d.kind === 'image_archive' ? ` (${d.details.extracted} photos extraites)` : '';
    toast(`${done.length > 1 ? `${done.length} fichiers importés. ` : ''}Détecté : ${d.label}${extra}. ${NEXT_STEP[d.category] || ''}`, 7000);
  }
  pageModels();
}

// ------------------------------------------------------------------ optimiser
async function pageOptimize(r) {
  if (!S.api) { page.innerHTML = `<div class="page-head"><div><h1>Optimiser</h1></div></div>${needApi()}`; return; }
  [S.models, S.configs, S.jobs] = await Promise.all([api('/api/models'), api('/api/configs'), api('/api/jobs')]);
  const tool = TOOLS[r.q.get('tool')] ? r.q.get('tool') : S.form.tool;
  if (tool !== S.form.tool) S.form.params = {};
  S.form.tool = tool;
  if (r.q.get('input')) S.form.params.input = r.q.get('input');
  if (!S.form.params.input) {
    const first = S.models.find((m) => m.name.endsWith('.ply') && !m.name.endsWith('.gsq.ply'));
    if (first) S.form.params.input = first.path;
  }
  const t = TOOLS[tool];
  for (const f of t.fields) if (S.form.params[f.k] === undefined && f.def !== undefined) S.form.params[f.k] = f.def;

  page.innerHTML = `
    <div class="page-head"><div><h1>Optimiser</h1><div class="muted">Choisissez une étape, réglez-la, lancez. Le journal s’affiche en direct.</div></div></div>
    <div class="tools">${Object.entries(TOOLS).map(([k, v]) => `<button class="tool ${k === tool ? 'sel' : ''}" data-tool="${k}">
      ${icon(k, 20)}<b>${v.title}</b><span>${v.short}</span></button>`).join('')}</div>
    <div class="opt-layout">
      <div class="card">
        <h2>${icon(tool, 18)} ${t.title}</h2>
        <div class="explain"><p>${t.what}</p><p class="muted small"><b>Quand ?</b> ${t.when}
          <a href="#/docs/${t.doc}">En savoir plus</a></p></div>
        <form id="tool-form" onsubmit="return false"></form>
        <div class="label" style="font-weight:600;margin:6px 0">Commande équivalente</div>
        <div class="cmd" id="cmd"><code>…</code><button class="btn ghost" id="copy-cmd" title="Copier">${icon('copy')}</button></div>
        <div class="row" style="margin-top:16px"><button class="btn primary lg" id="run">${icon('play')} Lancer</button>
          <span class="muted small" id="run-hint"></span></div>
      </div>
      <div>
        <div class="card" id="job-panel"></div>
        <div class="card"><h2>Historique</h2><div id="job-list"></div></div>
      </div>
    </div>`;
  $$('.tool').forEach((b) => b.addEventListener('click', () => go(`#/optimiser?tool=${b.dataset.tool}`)));
  renderForm();
  renderJobList();
  const jid = r.q.get('job') || S.currentJob;
  if (jid && S.jobs.find((j) => j.id === jid)) showJob(jid); else renderJobPanel(null);
  $('#run').addEventListener('click', runTool);
  $('#copy-cmd').addEventListener('click', () => copy($('#cmd code').textContent));
}

function fieldHtml(f, p) {
  if (f.show && !f.show(p)) return '';
  const help = f.help ? `<div class="help">${f.help}</div>` : '';
  const v = p[f.k] ?? '';
  switch (f.type) {
    case 'choice':
      return `<div class="field"><div class="label">${f.label}</div><div class="choices">${f.options.map(([val, name, d]) =>
        `<div class="choice ${String(v) === String(val) ? 'sel' : ''}" data-k="${f.k}" data-v="${val}"><b>${name}</b><span>${d}</span></div>`).join('')}</div>${help}</div>`;
    case 'range':
      return `<div class="field"><label>${f.label} : <span class="range-val" id="rv-${f.k}">${f.fmt(v)}</span></label>
        <input type="range" data-k="${f.k}" min="${f.min}" max="${f.max}" step="${f.step}" value="${v}">${help}</div>`;
    case 'check':
      return `<div class="field"><label class="check"><input type="checkbox" data-k="${f.k}" ${v ? 'checked' : ''}><span>${f.label}</span></label>${help}</div>`;
    case 'select':
      return `<div class="field"><label>${f.label}</label><select data-k="${f.k}">${f.options.map(([val, name]) =>
        `<option value="${val}" ${String(v) === String(val) ? 'selected' : ''}>${name}</option>`).join('')}</select>${help}</div>`;
    case 'configs':
      return `<div class="field"><label>${f.label}</label><select data-k="${f.k}">${S.configs.map((c) =>
        `<option ${c === v ? 'selected' : ''}>${c}</option>`).join('')}</select>
        <div class="help">Modifiable dans <code>${esc(v)}</code> (une configuration = une liste d’étapes).</div></div>`;
    default:
      return `<div class="field"><label>${f.label}</label><input type="${f.type === 'number' ? 'number' : 'text'}" data-k="${f.k}"
        value="${esc(v)}" placeholder="${esc(f.placeholder || '')}" ${f.step ? `step="${f.step}"` : ''}>${help}</div>`;
  }
}

function renderForm() {
  const t = TOOLS[S.form.tool];
  const p = S.form.params;
  const inputs = S.models.filter((m) => /\.(ply|splat|gsq)$/i.test(m.name) && !m.name.endsWith('.gsq.ply'));
  const inputField = t.noInput ? '' : `<div class="field"><label>Modèle d’entrée</label>
    ${inputs.length ? `<select data-k="input">${inputs.map((m) => `<option value="${esc(m.path)}" ${m.path === p.input ? 'selected' : ''}>
      ${esc(m.path)} — ${nf(m.count)} gaussiennes, ${size(m.size)}</option>`).join('')}</select>`
      : `<div class="empty" style="padding:14px">Aucun modèle. <a href="#/modeles">Importez-en un</a> ou générez la <a href="#/optimiser?tool=synthetic">scène de test</a>.</div>`}
    <div class="help">Les résultats sont rangés dans <code>results/&lt;nom de la scène&gt;/</code>.</div></div>`;
  const basic = t.fields.filter((f) => !f.adv).map((f) => fieldHtml(f, p)).join('');
  const adv = t.fields.filter((f) => f.adv).map((f) => fieldHtml(f, p)).join('');
  $('#tool-form').innerHTML = inputField + basic + (adv ? `<details class="adv" ${S.form.advOpen ? 'open' : ''}><summary>Réglages avancés</summary>${adv}</details>` : '');
  $('#tool-form details')?.addEventListener('toggle', (e) => { S.form.advOpen = e.target.open; });
  $$('.choice', $('#tool-form')).forEach((c) => c.addEventListener('click', () => { p[c.dataset.k] = c.dataset.v; renderForm(); }));
  $$('[data-k]', $('#tool-form')).forEach((el) => {
    if (el.classList.contains('choice')) return;
    el.addEventListener(el.type === 'range' || el.type === 'text' || el.type === 'number' ? 'input' : 'change', () => {
      p[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.type === 'range' ? Number(el.value) : el.value;
      if (el.type === 'range') { const f = t.fields.find((x) => x.k === el.dataset.k); $(`#rv-${f.k}`).textContent = f.fmt(Number(el.value)); }
      if (el.type === 'checkbox' || el.tagName === 'SELECT') renderForm(); else updateCmd();
    });
  });
  updateCmd();
}

let cmdTimer;
function updateCmd() {
  clearTimeout(cmdTimer);
  cmdTimer = setTimeout(async () => {
    const box = $('#cmd');
    if (!box) return;
    try {
      const r = await api('/api/run', { body: { tool: S.form.tool, params: S.form.params, dry: true } });
      box.classList.remove('err'); $('code', box).textContent = r.cmd; $('#run').disabled = false;
      $('#run-hint').textContent = r.outputs.length ? `→ ${r.outputs[0]}` : '';
    } catch (e) {
      box.classList.add('err'); $('code', box).textContent = e.message; $('#run').disabled = true; $('#run-hint').textContent = '';
    }
  }, 150);
}

async function runTool() {
  try {
    const j = await api('/api/run', { body: { tool: S.form.tool, params: S.form.params } });
    toast(`${j.title} lancé`);
    S.jobs.unshift(j); renderJobList(); showJob(j.id);
  } catch (e) { toast('Erreur : ' + e.message, 5000); }
}

function renderJobList() {
  const el = $('#job-list');
  if (!el) return;
  el.innerHTML = S.jobs.length ? S.jobs.slice(0, 12).map((j) => `<div class="job ${j.id === S.currentJob ? 'cur' : ''}" data-id="${j.id}">
    <div class="row"><b>${esc(j.title)}</b>${statusBadge(j.status)}<span class="spacer"></span><span class="muted small">${ago(j.start)}</span></div>
    <div class="muted small">${esc(j.input || '')}</div></div>`).join('') : '<div class="empty" style="padding:12px">Aucune tâche lancée.</div>';
  $$('.job', el).forEach((d) => d.addEventListener('click', () => showJob(d.dataset.id)));
}

function renderJobPanel(j) {
  const el = $('#job-panel');
  if (!el) return;
  if (!j) { el.innerHTML = `<h2>Suivi</h2><div class="empty">Réglez l’étape à gauche puis cliquez sur <b>Lancer</b>.<br>Le journal et les fichiers produits s’afficheront ici.</div>`; return; }
  const dur = ((j.end || Date.now() / 1000) - j.start);
  const next = TOOLS[j.tool]?.next ?? { train: 'analyze', convert: 'analyze' }[j.tool];
  el.innerHTML = `<div class="row"><h2 style="margin:0">${esc(j.title)}</h2>${statusBadge(j.status)}<span class="spacer"></span>
      <span class="muted small">${nf(dur, 1)} s</span></div>
    <div class="cmd" style="margin-top:10px"><code>${esc(j.cmd)}</code><button class="btn ghost" id="copy-job">${icon('copy')}</button></div>
    <div class="log" id="log"></div>
    ${j.status === 'running' ? '<div class="muted small">Calcul en cours… (la compression par dictionnaire peut prendre une minute)</div>' : ''}
    ${j.status === 'done' && j.outputs.length ? `<h3 style="margin-top:14px">Fichiers produits</h3><div class="outputs">${j.outputs.map((o) => `
      <div class="output"><code>${esc(o)}</code>
        ${viewable(viewPath(o)) && !o.endsWith('.gsq') ? `<a class="btn" href="#/visualiseur?models=${encodeURIComponent(o)}">${icon('eye')} Voir</a>` : ''}
        ${/\.(ply|splat|gsq)$/.test(o) && !o.endsWith('.gsq.ply') && next ? `<a class="btn primary" href="#/optimiser?tool=${next}&input=${encodeURIComponent(o)}">
          ${TOOLS[next].title} ce fichier ${icon('next')}</a>` : ''}
        ${/(summary\.md|analyze\.json)$/.test(o) ? `<a class="btn primary" href="#/resultats">${icon('pipeline')} Voir les résultats</a>` : ''}
        ${/benchmark\.md$/.test(o) ? `<a class="btn primary" href="#/benchmark">${icon('pipeline')} Voir le benchmark</a>` : ''}
        ${/\/images$|\.zip$|check\.json$/.test(o) ? `<a class="btn primary" href="#/modeles">Retour à la capture ${icon('next')}</a>` : ''}
      </div>`).join('')}</div>` : ''}
    ${j.status === 'error' && j.tool === 'train' ? '<div class="notice" style="margin-top:12px">Le modèle n’a pas été généré : le journal ci-dessus indique la cause et la marche à suivre (par exemple générer le modèle avec PostShot ou Polycam, puis importer le .ply obtenu dans Modèles).</div>'
      : j.status === 'error' ? '<div class="notice" style="margin-top:12px">La tâche a échoué : voir la fin du journal ci-dessus.</div>' : ''}`;
  $('#log').textContent = (S.logs[j.id] || []).join('\n');
  $('#log').scrollTop = 1e9;
  $('#copy-job').addEventListener('click', () => copy(j.cmd));
}
S.logs = {};

async function showJob(id) {
  S.currentJob = id;
  if (S.poll) clearInterval(S.poll);
  S.logs[id] = [];
  const tick = async () => {
    let j;
    try { j = await api(`/api/jobs/${id}?since=${S.logs[id].length}`); } catch { return; }
    S.logs[id].push(...j.log);
    const i = S.jobs.findIndex((x) => x.id === id);
    if (i >= 0) S.jobs[i] = j; else S.jobs.unshift(j);
    renderJobPanel(j);
    renderJobList();
    if (j.status !== 'running') {
      clearInterval(S.poll); S.poll = null;
      if (S.chain && S.chain.after === id && j.status === 'done') {
        const c = S.chain; S.chain = null;
        const nj = await api('/api/run', { body: { tool: c.tool, params: c.params } });
        toast(`${nj.title} lancé`); S.jobs.unshift(nj); showJob(nj.id);
      }
    }
  };
  await tick();
  if (S.jobs.find((x) => x.id === id)?.status === 'running') S.poll = setInterval(tick, 700);
}

// ------------------------------------------------------------------ résultats
async function pageResults() {
  if (!S.api) { page.innerHTML = `<div class="page-head"><div><h1>Résultats</h1></div></div>${needApi()}`; return; }
  const scenes = await api('/api/results');
  page.innerHTML = `<div class="page-head"><div><h1>Résultats</h1><div class="muted">Par scène : tableaux comparatifs,
    diagnostic, nettoyage et mesures du visualiseur. Cochez des fichiers pour les comparer.</div></div></div>
    ${scenes.length ? scenes.map(sceneCard).join('') : `<div class="card empty">Pas encore de résultats.
      <a href="#/optimiser?tool=pipeline">Lancez « Tout comparer »</a> sur un modèle.</div>`}`;
  $$('.compare').forEach((b) => b.addEventListener('click', () => {
    const sel = $$(`input[data-scene="${b.dataset.scene}"]:checked`).map((c) => c.value);
    if (!sel.length) return toast('Cochez au moins un fichier');
    go(`#/visualiseur?models=${encodeURIComponent(sel.join(','))}`);
  }));
}

function sceneCard(s) {
  const parts = [];
  if (s.summary) {
    const rows = s.summary;
    const main = (r) => (r.gsq_bytes ? ['gsq', r.gsq_bytes] : r.splat_bytes && !r.ply_bytes ? ['splat', r.splat_bytes] : ['ply', r.ply_bytes]);
    const maxB = Math.max(...rows.map((r) => main(r)[1] || 0));
    parts.push(`<h3>Comparaison des configurations</h3><div class="table-wrap"><table><thead><tr><th></th><th>Configuration</th>
      <th class="num">Gaussiennes</th><th class="num">SH</th><th class="num">Fichier</th><th class="num">Taille</th><th class="bar-cell"></th>
      <th class="num">Gain</th><th class="num">.splat</th></tr></thead><tbody>
      ${rows.map((r) => {
        const [ext, b] = main(r);
        const file = `results/${s.name}/${r.config}.${ext}`;
        const ratio = r[`${ext}_ratio`];
        return `<tr><td><input type="checkbox" data-scene="${esc(s.name)}" value="${esc(viewPath(file))}"></td>
          <td><b>${esc(r.config)}</b></td><td class="num">${nf(r.n_gaussians)}</td><td class="num">${r.sh_degree}</td>
          <td class="num"><span class="badge">${ext}</span></td><td class="num">${size(b)}</td>
          <td class="bar-cell"><div class="bar" style="width:${Math.max(2, (100 * b) / maxB)}%"></div></td>
          <td class="num"><b>×${nf(ratio, 1)}</b></td><td class="num muted">${r.splat_bytes ? size(r.splat_bytes) : '—'}</td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="help muted small" style="margin-top:6px">Gain = taille du PLY d’origine / taille du fichier. Les .gsq sont visualisés via leur version décodée (.gsq.ply).</div>`);
  } else if (s.files.length) {
    parts.push(`<h3>Fichiers produits</h3><div class="table-wrap"><table><tbody>${s.files.filter((f) => !f.name.endsWith('.gsq.ply')).map((f) =>
      `<tr><td style="width:30px"><input type="checkbox" data-scene="${esc(s.name)}" value="${esc(viewPath(f.path))}"></td>
       <td>${esc(f.name)}</td><td class="num">${size(f.size)}</td></tr>`).join('')}</tbody></table></div>`);
  }
  if (s.analyze) {
    const a = s.analyze;
    parts.push(`<h3 style="margin-top:18px">Diagnostic du modèle source</h3><div class="grid g4">
      <div class="stat"><div class="v">${nf(a.n_gaussians)}</div><div class="l">gaussiennes</div></div>
      <div class="stat"><div class="v">${a.file_size ? size(a.file_size) : '—'}</div><div class="l">taille</div></div>
      <div class="stat"><div class="v">${a.sh_degree}</div><div class="l">degré SH (${Math.round(100 * a.share_of_sh_rest_in_params)} % du poids)</div></div>
      <div class="stat"><div class="v">${nf(a.n_non_finite)}</div><div class="l">valeurs invalides</div></div></div>
      <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Candidats à la suppression</th><th class="num">Nombre</th><th class="num">Part</th></tr></thead><tbody>
      ${Object.entries(a.candidates).map(([k, v]) => `<tr><td><code>${esc(k)}</code></td><td class="num">${nf(v)}</td>
        <td class="num">${nf((100 * v) / a.n_gaussians, 1)} %</td></tr>`).join('')}</tbody></table></div>`);
  }
  for (const [f, rep] of Object.entries(s.reports || {})) {
    if (!rep?.steps) continue;
    parts.push(`<h3 style="margin-top:18px">Nettoyage — ${esc(f.replace('_report.json', ''))}</h3><div class="table-wrap"><table>
      <thead><tr><th>Filtre</th><th class="num">Retirées</th><th class="num">Restantes</th></tr></thead><tbody>
      ${rep.steps.map((st) => `<tr><td>${esc(st.filter)}</td><td class="num">${nf(st.removed)}</td><td class="num">${nf(st.remaining)}</td></tr>`).join('')}
      </tbody></table></div>`);
  }
  for (const b of s.benches || []) {
    const d = b.data;
    if (!d?.results) continue;
    parts.push(`<h3 style="margin-top:18px">Mesures navigateur — ${esc(d.env?.date?.slice(0, 16).replace('T', ' ') || b.file)}</h3>
      <div class="muted small">${esc(d.env?.gpu || '')} · ${(d.env?.resolution || []).join('×')} · SH ${d.env?.shDegree}</div>
      <div class="table-wrap"><table><thead><tr><th>Modèle</th><th class="num">Taille</th><th class="num">Gaussiennes</th>
      <th class="num">Chargement</th><th class="num">FPS moy.</th><th class="num">1 % low</th><th class="num">PSNR</th><th class="num">SSIM</th></tr></thead><tbody>
      ${d.results.map((r, i) => `<tr><td>${esc(r.name)}${i === 0 ? ' <span class="badge">réf.</span>' : ''}</td><td class="num">${size(r.bytes)}</td>
        <td class="num">${nf(r.splatCount)}</td><td class="num">${nf(r.totalMs)} ms</td><td class="num">${nf(r.fpsMean, 1)}</td>
        <td class="num">${nf(r.fpsLow1, 1)}</td><td class="num">${i ? nf(r.psnrMean, 2) + ' dB' : '—'}</td><td class="num">${i ? nf(r.ssimMean, 4) : '—'}</td></tr>`).join('')}
      </tbody></table></div>`);
  }
  return `<div class="card"><div class="row" style="margin-bottom:12px"><h2 style="margin:0">${esc(s.name)}</h2><span class="spacer"></span>
    <button class="btn primary compare" data-scene="${esc(s.name)}">${icon('eye')} Comparer la sélection</button></div>
    ${parts.join('') || '<div class="muted">Aucun résultat lisible.</div>'}</div>`;
}

// ------------------------------------------------------------------ benchmark
// Chiffres publiés, relevés tels qu'imprimés dans : Chen et al., « HAC: Hash-grid Assisted Context for
// 3D Gaussian Splatting Compression », arXiv:2403.14530 (Table 1). Méthodes entraînées sur des scènes réelles.
const LITERATURE = {
  source: 'https://arxiv.org/abs/2403.14530',
  datasets: {
    'Mip-NeRF360': [['3DGS (Kerbl et al.)', 27.49, 0.813, 0.222, 744.7], ['Scaffold-GS', 27.50, 0.806, 0.252, 253.9],
      ['Compact 3DGS (Lee et al.)', 27.08, 0.798, 0.247, 48.80], ['Compressed3D (Niedermayr et al.)', 26.98, 0.801, 0.238, 28.80],
      ['EAGLES', 27.15, 0.808, 0.238, 68.89], ['LightGaussian', 27.00, 0.799, 0.249, 44.54],
      ['Self-Organizing Gaussians (Morgenstern et al.)', 26.01, 0.772, 0.259, 23.90], ['Compact3D (Navaneet et al.)', 27.16, 0.808, 0.228, 50.30],
      ['HAC (bas débit)', 27.53, 0.807, 0.238, 15.26], ['HAC (haut débit)', 27.77, 0.811, 0.230, 21.87]],
    'Tanks & Temples': [['3DGS (Kerbl et al.)', 23.69, 0.844, 0.178, 431.0], ['Scaffold-GS', 23.96, 0.853, 0.177, 86.50],
      ['Compact 3DGS (Lee et al.)', 23.32, 0.831, 0.201, 39.43], ['Compressed3D (Niedermayr et al.)', 23.32, 0.832, 0.194, 17.28],
      ['EAGLES', 23.41, 0.840, 0.200, 34.00], ['LightGaussian', 22.83, 0.822, 0.242, 22.43],
      ['Self-Organizing Gaussians (Morgenstern et al.)', 22.78, 0.817, 0.211, 13.05], ['Compact3D (Navaneet et al.)', 23.47, 0.840, 0.188, 27.97],
      ['HAC (bas débit)', 24.04, 0.846, 0.187, 8.10], ['HAC (haut débit)', 24.40, 0.853, 0.177, 11.24]],
  },
};

async function pageBenchmark(r) {
  if (!S.api) { page.innerHTML = `<div class="page-head"><div><h1>Benchmark</h1></div></div>${needApi()}`; return; }
  const [models, suites, scenes] = await Promise.all([api('/api/models'), api('/api/suites'), api('/api/results')]);
  const inputs = models.filter((m) => m.type === 'gaussians' && m.dir.startsWith('data'));
  const done = scenes.filter((s) => s.benchmark);
  const sel = r.q.get('scene') && done.find((s) => s.name === r.q.get('scene')) ? r.q.get('scene') : done[0]?.name;
  page.innerHTML = `
    <div class="page-head"><div><h1>Benchmark des algorithmes</h1><div class="muted">Chaque variante est traitée, exportée, relue puis
      rendue depuis des vues de test : taille, qualité (PSNR, SSIM) et coût d’affichage (surdessin), pour savoir quels algorithmes valent le coup.</div></div></div>
    <div class="card">
      <h2>Lancer un benchmark</h2>
      <div class="grid g3">
        <div class="field"><label>Scène</label><select id="b-input">${inputs.map((m) =>
          `<option value="${esc(m.path)}">${esc(m.path)} — ${nf(m.count)} gaussiennes</option>`).join('') || '<option value="">aucun modèle dans data/</option>'}</select></div>
        <div class="field"><label>Suite de variantes</label><select id="b-suite">${suites.map((s) => `<option>${esc(s)}</option>`).join('')}</select></div>
        <div class="field"><label>Vues de test</label><input type="number" id="b-views" value="6" min="1" max="32">
          <div class="help">Plus de vues = mesure plus fiable, mais plus long (≈ 2 s par vue et par variante).</div></div>
      </div>
      <div class="field"><div class="label">Familles à tester</div><div class="row" id="b-fams"></div></div>
      <div class="row"><button class="btn primary lg" id="b-run" ${inputs.length ? '' : 'disabled'}>${icon('play')} Lancer le benchmark</button>
        <span class="muted small">Toute la suite sur la scène de test (300 000 gaussiennes) : ≈ 10 min. Le suivi s’affiche dans Optimiser.</span></div>
    </div>
    ${done.length ? `<div class="card"><div class="row"><h2 style="margin:0">Résultats</h2><span class="spacer"></span>
        <select id="b-scene" style="width:auto">${done.map((s) => `<option ${s.name === sel ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
        <div id="b-results"></div></div>` : '<div class="card empty">Pas encore de benchmark. Lancez-en un ci-dessus.</div>'}
    <div class="card">${literatureHtml()}</div>`;

  const loadFams = async () => {
    try {
      const suite = await (await fetch('/' + $('#b-suite').value)).json();
      const fams = [...new Set(suite.variants.map((v) => v.family))];
      $('#b-fams').innerHTML = fams.map((f) => `<label class="check" style="margin-right:12px"><input type="checkbox" value="${esc(f)}" checked><span>${esc(f)}
        <span class="muted small">(${suite.variants.filter((v) => v.family === f).length})</span></span></label>`).join('');
    } catch { $('#b-fams').textContent = 'suite illisible'; }
  };
  $('#b-suite').addEventListener('change', loadFams);
  await loadFams();
  $('#b-run').addEventListener('click', async () => {
    const all = $$('#b-fams input');
    const only = all.filter((c) => c.checked).map((c) => c.value);
    if (!only.length) return toast('Cochez au moins une famille');
    try {
      const j = await api('/api/run', { body: { tool: 'benchmark', params: { input: $('#b-input').value, suite: $('#b-suite').value,
        views: $('#b-views').value, only: only.length === all.length ? null : only } } });
      toast('Benchmark lancé'); go(`#/optimiser?job=${j.id}`);
    } catch (e) { toast('Erreur : ' + e.message, 6000); }
  });
  if (done.length) {
    const show = (name) => renderBenchmark(done.find((s) => s.name === name));
    $('#b-scene').addEventListener('change', (e) => show(e.target.value));
    show(sel);
  }
}

function renderBenchmark(scene) {
  const B = scene.benchmark;
  const rows = B.rows;
  const ok = rows.filter((x) => x.status === 'ok');
  const fams = [...new Set(rows.map((x) => x.family))];
  const env = B.env;
  const base = `/results/${scene.name}/benchmark/img/`;
  $('#b-results').innerHTML = `
    <div class="muted small" style="margin:6px 0 14px">${esc(env.date)} · entrée ${size(env.input_bytes)}, ${nf(env.input_n)} gaussiennes ·
      référence qualité : ${nf(env.reference_n)} gaussiennes · ${env.views} vues ${env.size.join('×')} · ${nf(env.duration_s / 60, 1)} min</div>
    <div class="row" style="margin-bottom:6px"><span class="small muted">Mettre une famille en évidence :</span>
      ${fams.map((f) => `<button class="btn ghost small fam-chip" data-f="${esc(f)}">${esc(f)}</button>`).join('')}</div>
    <div class="viz" id="b-chart"></div>
    <div class="md" style="padding:0;margin-top:10px">${renderMarkdown('### Ce que dit le benchmark\n\n' + B.summary)}</div>
    <h3 style="margin-top:18px">Toutes les variantes</h3>
    <div class="table-wrap"><table><thead><tr><th>Famille</th><th>Variante</th><th class="num">Taille</th><th class="num">Facteur</th>
      <th class="num">Gaussiennes</th><th class="num">PSNR moy. (pire)</th><th class="num">SSIM</th><th class="num">Surdessin</th><th>Pareto</th></tr></thead>
      <tbody>${rows.map((x) => x.status === 'ok' ? `<tr class="b-row" data-n="${esc(x.name)}" style="cursor:pointer">
        <td class="muted small">${esc(x.family)}</td><td><b>${esc(x.name)}</b> <span class="badge">${esc(x.format)}</span></td>
        <td class="num">${size(x.bytes)}</td><td class="num">×${nf(x.ratio, 1)}</td><td class="num">${nf(x.n)}</td>
        <td class="num">${nf(x.psnr, 2)} <span class="muted">(${nf(x.psnr_min, 1)})</span></td><td class="num">${nf(x.ssim, 4)}</td>
        <td class="num">${nf(x.overdraw, 1)} <span class="muted small">${env.reference_overdraw ? `(${nf((100 * x.overdraw) / env.reference_overdraw)} %)` : ''}</span></td>
        <td>${x.pareto ? '<span class="badge ok">★ meilleur compromis</span>' : ''}</td></tr>`
      : `<tr><td class="muted small">${esc(x.family)}</td><td>${esc(x.name)}</td><td colspan="7" class="muted small">
          ${x.status === 'skipped' ? 'ignorée' : 'erreur'} : ${esc(x.reason || '')}</td></tr>`).join('')}</tbody></table></div>
    <div class="help muted small" style="margin-top:6px">PSNR : > 35 dB différence invisible, 30–35 dB légère, < 30 dB visible.
      Surdessin = fragments composés par pixel (coût d’affichage ; entre parenthèses, par rapport à la référence). Cliquez une ligne pour comparer les images.</div>
    <div id="b-compare" style="margin-top:14px"></div>`;
  drawRD(ok, null);
  $$('.fam-chip').forEach((b) => b.addEventListener('click', () => {
    const on = !b.classList.contains('sel');
    $$('.fam-chip').forEach((x) => x.classList.remove('sel'));
    if (on) b.classList.add('sel');
    drawRD(ok, on ? b.dataset.f : null);
  }));
  const compare = (name) => {
    const x = rows.find((y) => y.name === name);
    $('#b-compare').innerHTML = `<h3>${esc(name)} — ${size(x.bytes)}, ${nf(x.psnr, 2)} dB</h3><div class="grid g2">
      ${[0, 1].map((i) => `<figure style="margin:0"><img src="${base}_reference_${i}.png" style="width:100%;border-radius:6px">
        <figcaption class="small muted">Référence · vue ${i + 1}</figcaption></figure>
        <figure style="margin:0"><img src="${base}${encodeURIComponent(name)}_${i}.png" style="width:100%;border-radius:6px">
        <figcaption class="small muted">${esc(name)} · vue ${i + 1}</figcaption></figure>`).join('')}</div>`;
    $('#b-compare').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  $$('.b-row').forEach((tr) => tr.addEventListener('click', () => compare(tr.dataset.n)));
}

// Courbe débit–distorsion : taille (échelle log) vs PSNR. Bleu = front de Pareto (nommé),
// orange = famille mise en évidence, gris = le reste (3 couleurs max : lisible pour les daltoniens).
function drawRD(rows, fam) {
  const el = $('#b-chart');
  if (!rows.length) { el.innerHTML = ''; return; }
  const W = 760, H = 380, m = { l: 52, r: 24, t: 16, b: 44 };
  const mb = (b) => b / 1048576;
  const xs = rows.map((x) => Math.log10(mb(x.bytes)));
  const x0 = Math.floor(Math.min(...xs) * 2) / 2 - 0.1, x1 = Math.ceil(Math.max(...xs) * 2) / 2 + 0.1;
  // axe borné à 20 dB : en dessous (modèle brut plein de floaters…) le point est posé au bas du graphique
  // avec un triangle « hors échelle », pour ne pas écraser la zone utile.
  const y0 = Math.max(20, Math.floor(Math.min(...rows.map((x) => x.psnr)) / 5) * 5), y1 = 50;
  const X = (v) => m.l + ((Math.log10(mb(v)) - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500].filter((t) => Math.log10(t) >= x0 && Math.log10(t) <= x1);
  const yt = []; for (let v = y0; v <= y1; v += 5) yt.push(v);
  const front = rows.filter((x) => x.pareto).sort((a, b) => a.bytes - b.bytes);
  const pts = [...rows].sort((a, b) => (a.pareto - b.pareto) || ((a.family === fam) - (b.family === fam)));
  const cls = (x) => (x.family === fam ? 'hi' : x.pareto ? 'pa' : 'mu');
  const mark = (x) => (x.psnr >= y0
    ? `<circle class="pt ${cls(x)}" cx="${X(x.bytes)}" cy="${Y(x.psnr)}" r="5" data-n="${esc(x.name)}"/>`
    : `<path class="pt ${cls(x)}" d="M${X(x.bytes) - 6},${Y(y0) - 9}h12l-6,9z" data-n="${esc(x.name)}"/>`);
  // étiquettes du front : 4 positions candidates par point, la première qui ne chevauche ni une
  // étiquette déjà posée ni un point du front est retenue (placement glouton)
  const placed = [];
  const frontPts = front.map((x) => [X(x.bytes), Y(Math.max(x.psnr, y0))]);
  const hits = (b) => placed.some((p) => b.x < p.x + p.w && b.x + b.w > p.x && b.y < p.y + p.h && b.y + b.h > p.y)
    || frontPts.some(([px, py]) => px > b.x - 6 && px < b.x + b.w + 6 && py > b.y - 6 && py < b.y + b.h + 6)
    || b.x < m.l || b.x + b.w > W - 4 || b.y < 2;
  const labels = front.map((x) => {
    const [px, py] = [X(x.bytes), Y(Math.max(x.psnr, y0))];
    const w = x.name.length * 6.4, h = 12;
    const cand = [[px + 9, py - 6], [px - 9 - w, py - 6], [px - w / 2, py - 20], [px - w / 2, py + 9],
                  [px + 9, py + 8], [px - 9 - w, py + 8], [px + 9, py - 20], [px - 9 - w, py - 20]];
    const c = cand.find(([bx, by]) => !hits({ x: bx, y: by, w, h })) || cand[0];
    placed.push({ x: c[0], y: c[1], w, h });
    return `<text class="lab" x="${c[0]}" y="${c[1] + 10}">${esc(x.name)}</text>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Taille du fichier en fonction de la qualité (PSNR) pour chaque variante">
    ${yt.map((v) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tick" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`).join('')}
    ${ticks.map((t) => `<text class="tick" x="${X(t * 1048576)}" y="${H - m.b + 18}" text-anchor="middle">${t >= 1 ? t : String(t).replace('.', ',')}</text>`).join('')}
    <line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>
    ${[35, 30].filter((v) => v > y0).map((v) => `<line class="thr" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>
      <text class="tick" x="${W - m.r}" y="${Y(v) - 5}" text-anchor="end">${v === 35 ? 'invisible ≥ 35 dB' : 'acceptable ≥ 30 dB'}</text>`).join('')}
    <text class="axt" x="${(W + m.l) / 2}" y="${H - 6}" text-anchor="middle">Taille du fichier (Mo, échelle log) — vers la gauche = plus léger</text>
    <text class="axt" transform="translate(14 ${(H - m.b + m.t) / 2}) rotate(-90)" text-anchor="middle">PSNR (dB) — plus haut = plus fidèle</text>
    ${front.length > 1 ? `<polyline class="front" points="${front.map((x) => `${X(x.bytes)},${Y(Math.max(x.psnr, y0))}`).join(' ')}"/>` : ''}
    ${pts.map(mark).join('')}
    ${labels.join('')}
  </svg>
  <div class="legend small"><span><i class="sw pa"></i>meilleurs compromis (front de Pareto)</span>
    ${fam ? `<span><i class="sw hi"></i>${esc(fam)}</span>` : ''}<span><i class="sw mu"></i>autres variantes</span>
    ${rows.some((x) => x.psnr < y0) ? `<span>▼ sous ${y0} dB (hors échelle)</span>` : ''}</div>
  <div class="tip" id="b-tip" hidden></div>`;
  const tip = $('#b-tip');
  $$('.pt', el).forEach((c) => {
    c.addEventListener('mouseenter', () => {
      const x = rows.find((y) => y.name === c.dataset.n);
      tip.innerHTML = `<b>${esc(x.name)}</b><br><span class="muted">${esc(x.family)}</span><br>${size(x.bytes)} · ×${nf(x.ratio, 1)}<br>
        PSNR ${nf(x.psnr, 2)} dB (pire vue ${nf(x.psnr_min, 1)}) · SSIM ${nf(x.ssim, 3)}`;
      tip.hidden = false;
      const b = c.getBoundingClientRect(), p = el.getBoundingClientRect();
      tip.style.left = `${Math.min(b.left - p.left + 12, p.width - 230)}px`;
      tip.style.top = `${b.top - p.top - 10}px`;
    });
    c.addEventListener('mouseleave', () => { tip.hidden = true; });
  });
}

function literatureHtml() {
  const L = LITERATURE;
  return `<h2>Comparaison avec les méthodes publiées</h2>
    <div class="muted small" style="margin-bottom:10px">Chiffres rapportés par les auteurs, relevés dans
      <a href="${L.source}" target="_blank">Chen et al., HAC, arXiv:2403.14530, tableau 1</a>. Ces méthodes ré-entraînent le modèle sur
      les photos d’origine et sont évaluées sur des scènes réelles (jeux de données publics), contre les photos de test.
      Nos variantes sont des post-traitements sans ré-entraînement, mesurées par rapport au modèle de départ :
      <b>les facteurs se comparent, les PSNR non</b>. Pour une comparaison directe, lancer notre benchmark sur un modèle 3DGS
      pré-entraîné d’une de ces scènes.</div>
    <div class="grid g2">${Object.entries(L.datasets).map(([ds, rs]) => `<div><h3>${esc(ds)}</h3><div class="table-wrap"><table>
      <thead><tr><th>Méthode</th><th class="num">PSNR</th><th class="num">SSIM</th><th class="num">LPIPS</th><th class="num">Taille</th><th class="num">÷ 3DGS</th></tr></thead>
      <tbody>${rs.map(([n, p, s, l, mbv]) => `<tr><td>${esc(n)}</td><td class="num">${nf(p, 2)}</td><td class="num">${nf(s, 3)}</td>
        <td class="num">${nf(l, 3)}</td><td class="num">${nf(mbv, 1)} Mo</td><td class="num">×${nf(rs[0][4] / mbv, 1)}</td></tr>`).join('')}</tbody></table></div></div>`).join('')}</div>`;
}

// ------------------------------------------------------------------ visualiseur
async function pageViewer(r) {
  const models = (r.q.get('models') || '').split(',').filter(Boolean);
  const src = models.length ? viewerUrl(models) : '/viewer/';
  page.innerHTML = `<div class="page-head"><div><h1>Visualiseur</h1><div class="muted">${models.length
    ? `${models.length} modèle${models.length > 1 ? 's' : ''} chargé${models.length > 1 ? 's' : ''} — cliquez sur un nom à gauche pour l’afficher, ou lancez le benchmark.`
    : 'Choisissez des modèles depuis <a href="#/modeles">Modèles</a> ou <a href="#/resultats">Résultats</a>, ou chargez un fichier local dans le panneau.'}</div></div>
    <a class="btn" href="${src}" target="_blank">${icon('ext')} Ouvrir en plein écran</a></div>
    <div class="notice small" style="margin-bottom:12px">Pour des mesures fiables : gardez cette fenêtre visible au premier plan pendant le
      benchmark (un onglet caché suspend le rendu) et branchez le portable sur secteur.</div>
    <iframe class="viewer-frame" src="${src}" allow="fullscreen"></iframe>`;
}

// ------------------------------------------------------------------ documentation
async function pageDocs(r) {
  if (!S.docs.length) {
    S.docs = S.api ? await api('/api/docs') : [
      { file: 'README.md', title: 'Présentation du projet' },
      ...['01_fondements_3dgs', '02_capture_generation', '03_optimisation', '04_integration_mesures', '05_guide_bonnes_pratiques', '06_plan_de_travail']
        .map((f) => ({ file: `docs/${f}.md`, title: f.slice(3).replace(/_/g, ' ') }))];
  }
  const file = r.rest || 'README.md';
  page.innerHTML = `<div class="docs">
    <nav class="doc-list">${S.docs.map((d) => `<a href="#/docs/${d.file}" class="${d.file === file ? 'active' : ''}">${esc(d.title)}</a>`).join('')}</nav>
    <article class="card md" id="md">Chargement…</article>
    <nav class="toc" id="toc"></nav></div>`;
  const res = await fetch('/' + file);
  if (!res.ok) { $('#md').textContent = 'Document introuvable.'; return; }
  $('#md').innerHTML = renderMarkdown(await res.text());
  // liens internes entre documents
  $$('#md a').forEach((a) => {
    const href = a.getAttribute('href') || '';
    if (/^https?:/.test(href)) { a.target = '_blank'; return; }
    const m = href.match(/([\w./-]+\.md)/);
    if (m) {
      const target = m[1].startsWith('docs/') || m[1] === 'README.md' ? m[1] : (file.includes('/') ? 'docs/' : '') + m[1];
      a.setAttribute('href', `#/docs/${target}`);
    }
  });
  const heads = $$('#md h2, #md h3');
  heads.forEach((h, i) => { h.id = 'h-' + i; });
  $('#toc').innerHTML = heads.length ? `<div class="muted small" style="padding:0 10px 6px;font-weight:600">Sur cette page</div>` +
    heads.map((h) => `<a href="#" data-target="${h.id}" class="${h.tagName.toLowerCase()}">${esc(h.textContent)}</a>`).join('') : '';
  $$('#toc a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); $('#' + a.dataset.target).scrollIntoView({ behavior: 'smooth' }); }));
}

function renderMarkdown(src) {
  const math = [];
  const keep = (tex, display) => { math.push([tex, display]); return `@@M${math.length - 1}@@`; };
  // protège le code des remplacements de formules
  const code = [];
  src = src.replace(/```[\s\S]*?```|`[^`\n]+`/g, (m) => { code.push(m); return `@@C${code.length - 1}@@`; });
  src = src.replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => keep(t, true)).replace(/\$([^$\n]+?)\$/g, (_, t) => keep(t, false));
  src = src.replace(/@@C(\d+)@@/g, (_, i) => code[i]);
  let html = window.marked ? marked.parse(src) : `<pre>${esc(src)}</pre>`;
  html = html.replace(/@@M(\d+)@@/g, (_, i) => {
    const [tex, display] = math[i];
    try { return window.katex ? katex.renderToString(tex, { displayMode: display, throwOnError: false }) : esc(tex); } catch { return esc(tex); }
  });
  return html;
}

// ------------------------------------------------------------------ démarrage
function initTheme() {
  const saved = (() => { try { return localStorage.getItem('theme'); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $('#theme-toggle').addEventListener('click', (e) => {
    e.preventDefault();
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('theme', document.documentElement.dataset.theme); } catch { /* stockage indisponible */ }
  });
}

(async function init() {
  initTheme();
  try { await api('/api/health'); S.api = true; } catch { S.api = false; }
  $('#server-status').innerHTML = S.api ? '<span class="dot ok"></span>Serveur connecté' : '<span class="dot err"></span>Lecture seule (lancer app.py)';
  route();
})();
