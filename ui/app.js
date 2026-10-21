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
const ROUTES = { accueil: pageHome, modeles: pageModels, optimiser: pageOptimize, resultats: pageResults,
                 visualiseur: pageViewer, docs: pageDocs };
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

// ------------------------------------------------------------------ modèles
async function pageModels() {
  if (!S.api) { page.innerHTML = `<div class="page-head"><div><h1>Modèles</h1></div></div>${needApi()}`; return; }
  S.models = await api('/api/models');
  page.innerHTML = `
    <div class="page-head"><div><h1>Modèles</h1><div class="muted">Fichiers de <code>data/</code> (importés) et <code>results/</code> (produits par les outils).</div></div></div>
    <label class="drop" id="drop">
      <input type="file" id="file" accept=".ply,.splat,.gsq,.ksplat,.spz" multiple hidden>
      <strong>${icon('upload', 20)} Glissez un modèle ici ou cliquez pour choisir</strong>
      <span class="muted">.ply (PostShot, Polycam, Luma, Brush, gsplat…), .splat, .ksplat, .spz — copié dans <code>data/</code></span>
      <div class="progress" id="prog" hidden><div></div></div>
    </label>
    <div class="card" style="margin-top:16px">
      <div class="row" style="margin-bottom:10px"><h2 style="margin:0">${S.models.length} fichier${S.models.length > 1 ? 's' : ''}</h2><span class="spacer"></span>
        <input type="text" class="search" id="filter" placeholder="Filtrer par nom ou dossier…"></div>
      <div id="model-table"></div>
    </div>`;
  renderModelTable('');
  $('#filter').addEventListener('input', (e) => renderModelTable(e.target.value.toLowerCase()));
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => uploadFiles(e.dataTransfer.files));
  $('#file').addEventListener('change', (e) => uploadFiles(e.target.files));
}

function renderModelTable(filter) {
  const rows = S.models.filter((m) => !filter || m.path.toLowerCase().includes(filter));
  if (!rows.length) {
    $('#model-table').innerHTML = `<div class="empty">Aucun modèle${filter ? ' correspondant' : ''}. Importez un .ply ou lancez
      <a href="#/optimiser?tool=synthetic">la scène de test</a>.</div>`;
    return;
  }
  const maxSize = Math.max(...rows.map((m) => m.size));
  $('#model-table').innerHTML = `<div class="table-wrap"><table><thead><tr><th>Nom</th><th>Dossier</th><th class="num">Gaussiennes</th>
    <th class="num">Taille</th><th class="bar-cell"></th><th>Modifié</th><th class="num">Actions</th></tr></thead><tbody>
    ${rows.map((m) => `<tr>
      <td><b>${esc(m.name)}</b> <span class="badge">${esc(m.kind)}</span></td>
      <td class="muted small">${esc(m.dir)}</td>
      <td class="num">${nf(m.count)}</td><td class="num">${size(m.size)}</td>
      <td class="bar-cell"><div class="bar" style="width:${Math.max(2, (100 * m.size) / maxSize)}%"></div></td>
      <td class="muted small">${ago(m.mtime)}</td>
      <td class="num" style="white-space:nowrap">
        <a class="btn ghost" title="Optimiser" href="#/optimiser?tool=${m.dir.startsWith('data') ? 'analyze' : 'clean'}&input=${encodeURIComponent(m.path)}">${icon('next')} Optimiser</a>
        <a class="btn ghost" title="Voir dans le visualiseur" href="#/visualiseur?models=${encodeURIComponent(viewPath(m.path))}">${icon('eye')}</a>
        <button class="btn ghost danger" title="Supprimer" data-del="${esc(m.path)}">${icon('trash')}</button>
      </td></tr>`).join('')}</tbody></table></div>`;
  $$('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(`Supprimer définitivement ${b.dataset.del} ?`)) return;
    await api('/api/delete', { body: { path: b.dataset.del } });
    toast('Fichier supprimé'); pageModels();
  }));
}

async function uploadFiles(files) {
  const prog = $('#prog');
  for (const f of files) {
    prog.hidden = false;
    await new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', '/api/upload?name=' + encodeURIComponent(f.name));
      x.upload.onprogress = (e) => { prog.firstElementChild.style.width = `${(100 * e.loaded) / e.total}%`; };
      x.onload = () => (x.status < 300 ? resolve() : reject(new Error(JSON.parse(x.responseText).error)));
      x.onerror = () => reject(new Error('échec de l’envoi'));
      x.send(f);
    }).then(() => toast(`${f.name} importé dans data/`)).catch((e) => toast(`Erreur : ${e.message}`, 5000));
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
  const next = TOOLS[j.tool]?.next;
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
      </div>`).join('')}</div>` : ''}
    ${j.status === 'error' ? '<div class="notice" style="margin-top:12px">La tâche a échoué : voir la fin du journal ci-dessus.</div>' : ''}`;
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
