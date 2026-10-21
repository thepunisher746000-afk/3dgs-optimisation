// Banc de mesure 3DGS : chargement, fluidité (temps de trame) et qualité (PSNR/SSIM) de plusieurs
// versions d'une scène sur un parcours de caméra identique. Rendu : @mkkellogg/gaussian-splats-3d
// en mode « non autonome » (on pilote nous-mêmes la boucle de rendu pour mesurer chaque trame).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import * as GS from '@mkkellogg/gaussian-splats-3d';
import { psnr, ssim, frameStats } from './metrics.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage');

// ------------------------------------------------------------------ rendu
const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setClearColor(0x000000, 1);
stage.prepend(renderer.domElement);

const camera = new THREE.PerspectiveCamera(50, 16 / 9, 0.05, 5000);
camera.position.set(0, -2, -6);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, -0.5, 0);
controls.enableDamping = false;
const emptyScene = new THREE.Scene();

let viewer = null;
let current = null;        // modèle affiché
let frameHook = null;      // callback du benchmark (prend le contrôle de la caméra)
let models = [];           // {name, file?, url?}
let poses = [];            // {position:[x,y,z], target:[x,y,z]}
let lastResults = null;

function setUp() {
  const v = $('up').value.split(',').map(Number);
  camera.up.set(v[0], v[1], v[2]);
  controls.update();
}

function setResolution() {
  let w, h;
  if ($('res').value === 'auto') {
    w = stage.clientWidth; h = stage.clientHeight;
  } else {
    [w, h] = $('res').value.split('x').map(Number);
  }
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// --------------------------------------------------------- boucle de rendu
let last = performance.now();
let hudAcc = 0, hudFrames = 0;
function tick(now) {
  requestAnimationFrame(tick);
  const dt = now - last;
  last = now;
  if (frameHook) frameHook(now, dt); else controls.update();
  if (viewer) { viewer.update(); viewer.render(); } else renderer.render(emptyScene, camera);
  hudAcc += dt; hudFrames++;
  if (hudAcc > 500) {
    const n = viewer?.splatMesh?.getSplatCount?.() ?? 0;
    $('hud').textContent = `${(1000 * hudFrames / hudAcc).toFixed(1)} FPS · ${n.toLocaleString('fr-FR')} gaussiennes` +
      (current ? ` · ${current.name}` : '');
    hudAcc = 0; hudFrames = 0;
  }
}
requestAnimationFrame(tick);

const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));
async function settle(minFrames = 20, maxMs = 5000) {
  // attend que le tri (asynchrone, dans un worker) soit terminé pour la pose courante
  const t0 = performance.now();
  for (let i = 0; ; i++) {
    await nextFrame();
    if (i >= minFrames && viewer && !viewer.sortRunning) break;
    if (performance.now() - t0 > maxMs && i >= 2) break;
  }
  await nextFrame();
}

// ---------------------------------------------------------- chargement
const FORMATS = { ply: GS.SceneFormat.Ply, splat: GS.SceneFormat.Splat, ksplat: GS.SceneFormat.KSplat, spz: GS.SceneFormat.Spz };
const formatOf = (name) => FORMATS[name.split('?')[0].split('.').pop().toLowerCase()];

async function loadModel(m) {
  if (viewer) { const v = viewer; viewer = null; await v.dispose(); }
  current = m;
  const t0 = performance.now();
  const buf = m.file ? await m.file.arrayBuffer()
                     : await (await fetch(m.url, { cache: 'no-store' })).arrayBuffer();
  const t1 = performance.now();
  const blobUrl = URL.createObjectURL(new Blob([buf]));
  const v = new GS.Viewer({
    selfDrivenMode: false, renderer, camera, useBuiltInControls: false, rootElement: stage,
    sharedMemoryForWorkers: false, gpuAcceleratedSort: false, ignoreDevicePixelRatio: true,
    sphericalHarmonicsDegree: Number($('shDeg').value), dynamicScene: false,
    sceneRevealMode: GS.SceneRevealMode.Instant, logLevel: GS.LogLevel.None,
  });
  await v.addSplatScene(blobUrl, {
    format: formatOf(m.name), showLoadingUI: false, progressiveLoad: false,
    splatAlphaRemovalThreshold: Number($('alphaThr').value),
  });
  const t2 = performance.now();
  viewer = v;
  await settle(1);
  const t3 = performance.now();
  URL.revokeObjectURL(blobUrl);
  return {
    name: m.name, bytes: buf.byteLength, splatCount: v.splatMesh.getSplatCount(),
    readMs: t1 - t0, decodeUploadMs: t2 - t1, firstFrameMs: t3 - t2, totalMs: t3 - t0,
  };
}

// --------------------------------------------------------------- poses
function applyPose(p) {
  camera.position.fromArray(p.position);
  controls.target.fromArray(p.target);
  camera.lookAt(controls.target);
}

function currentPose() {
  return { position: camera.position.toArray(), target: controls.target.toArray() };
}

function orbitPoses(n = 8) {
  const t = controls.target.clone();
  const off = camera.position.clone().sub(t);
  const r = off.length();
  const up = camera.up.clone().normalize();
  const a = Math.abs(up.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1);
  const e1 = new THREE.Vector3().crossVectors(up, a).normalize();
  const e2 = new THREE.Vector3().crossVectors(up, e1);
  const out = [];
  for (let i = 0; i < n; i++) {
    const th = (2 * Math.PI * i) / n;
    const el = THREE.MathUtils.degToRad(i % 2 ? 30 : 12);
    const p = t.clone()
      .addScaledVector(e1, r * Math.cos(el) * Math.cos(th))
      .addScaledVector(e2, r * Math.cos(el) * Math.sin(th))
      .addScaledVector(up, r * Math.sin(el));
    out.push({ position: p.toArray(), target: t.toArray() });
  }
  return out;
}

function poseAt(u) {  // u dans [0, poses.length) : interpolation linéaire en boucle
  const i = Math.floor(u) % poses.length;
  const j = (i + 1) % poses.length;
  const f = u - Math.floor(u);
  const s = f * f * (3 - 2 * f);  // smoothstep
  const lerp = (a, b) => a.map((v, k) => v + (b[k] - v) * s);
  return { position: lerp(poses[i].position, poses[j].position), target: lerp(poses[i].target, poses[j].target) };
}

// ----------------------------------------------------------- captures
const grabCanvas = document.createElement('canvas');
const grabCtx = grabCanvas.getContext('2d', { willReadFrequently: true });
function grab() {
  const src = renderer.domElement;
  grabCanvas.width = src.width; grabCanvas.height = src.height;
  grabCtx.drawImage(src, 0, 0);
  return grabCtx.getImageData(0, 0, src.width, src.height);
}
function thumb(img) {
  const c = document.createElement('canvas');
  c.width = 160; c.height = Math.round(160 * img.height / img.width);
  const tmp = document.createElement('canvas');
  tmp.width = img.width; tmp.height = img.height;
  tmp.getContext('2d').putImageData(img, 0, 0);
  c.getContext('2d').drawImage(tmp, 0, 0, c.width, c.height);
  return { small: c.toDataURL('image/jpeg', 0.8), png: $('keepPng').checked ? tmp.toDataURL('image/png') : null };
}

// ------------------------------------------------------------ benchmark
async function flyPath(durationMs) {
  const dts = [];
  await new Promise((resolve) => {
    let t0 = null;
    frameHook = (now, dt) => {
      if (t0 === null) t0 = now; else dts.push(dt);
      const u = ((now - t0) / durationMs) * poses.length;
      if (now - t0 >= durationMs) { frameHook = null; resolve(); return; }
      applyPose(poseAt(u));
    };
  });
  return dts;
}

let initialLoad = null;
async function benchmark() {
  if (!models.length) return log('Aucun modèle.');
  if (initialLoad) await initialLoad.catch(() => {});  // ne pas lancer deux chargements à la fois
  if (poses.length < 2) { poses = orbitPoses(8); updatePoseCount(); log('Poses : orbite automatique (8).'); }
  setResolution();
  const env = {
    date: new Date().toISOString(), userAgent: navigator.userAgent, gpu: gpuName(),
    resolution: [renderer.domElement.width, renderer.domElement.height],
    shDegree: Number($('shDeg').value), durationS: Number($('duration').value), poses,
  };
  const results = [];
  let refShots = null;
  $('rows').innerHTML = '';
  $('run').disabled = true;
  try {
    for (const m of models) {
      log(`Chargement ${m.name}…`);
      const r = await loadModel(m);
      applyPose(poses[0]);
      await settle(30);
      const dts = [];
      for (let k = 0; k < Number($('repeats').value); k++) {
        log(`  parcours ${k + 1}…`);
        dts.push(...(await flyPath(Number($('duration').value) * 1000)));
      }
      Object.assign(r, frameStats(dts.slice(5)));
      log('  captures + qualité…');
      const shots = [];
      for (const p of poses) {
        applyPose(p);
        await settle(20);
        shots.push(grab());
      }
      if (!refShots) refShots = shots;
      r.psnr = []; r.ssim = [];
      shots.forEach((img, i) => {
        r.psnr.push(psnr(refShots[i].data, img.data));
        r.ssim.push(ssim(refShots[i].data, img.data, img.width, img.height));
      });
      r.psnrMean = mean(r.psnr.filter(Number.isFinite));
      r.ssimMean = mean(r.ssim);
      r.shots = shots.map(thumb);
      results.push(r);
      addRow(r, results.length === 1);
    }
    lastResults = { env, results };
    $('download').disabled = false;
    log('Terminé.');
    await saveToServer(lastResults);
  } catch (e) {
    console.error(e); log('Erreur : ' + e.message);
  } finally {
    frameHook = null;
    $('run').disabled = false;
  }
}

// ------------------------------------------------------------------- UI
const mean = (a) => (a.length ? a.reduce((p, q) => p + q, 0) / a.length : NaN);
const fmt = (v, d = 1) => (v === undefined || Number.isNaN(v) ? '—' : v === Infinity ? '∞' : v.toFixed(d));
const mo = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' Mo' : (b / 1024).toFixed(0) + ' Ko');

function addRow(r, isRef) {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${r.name}${isRef ? ' <span class="hint">(réf.)</span>' : ''}</td><td>${mo(r.bytes)}</td>
    <td>${r.splatCount.toLocaleString('fr-FR')}</td><td>${fmt(r.readMs, 0)}</td><td>${fmt(r.decodeUploadMs, 0)}</td>
    <td>${fmt(r.firstFrameMs, 0)}</td><td>${fmt(r.fpsMean)}</td><td>${fmt(r.fpsLow1)}</td><td>${fmt(r.msP95)}</td>
    <td>${isRef ? '—' : fmt(r.psnrMean, 2)}</td><td>${isRef ? '—' : fmt(r.ssimMean, 4)}</td>
    <td class="thumbs">${r.shots.slice(0, 4).map((s) => `<img src="${s.small}">`).join('')}</td>`;
  $('rows').appendChild(tr);
}

function log(msg) { $('log').textContent += msg + '\n'; $('log').scrollTop = 1e9; }
function updatePoseCount() { $('poseCount').textContent = `${poses.length} pose${poses.length > 1 ? 's' : ''}`; }
function renderModels() {
  $('models').innerHTML = '';
  models.forEach((m, i) => {
    const li = document.createElement('li');
    li.textContent = m.name + (m.file ? ` (${mo(m.file.size)})` : '');
    if (i === 0) li.className = 'ref';
    li.onclick = async () => {
      log(`Affichage ${m.name}…`);
      try { const r = await loadModel(m); log(`  ${r.splatCount} gaussiennes, ${fmt(r.totalMs, 0)} ms`); }
      catch (e) { console.error(e); log('Erreur : ' + e.message); }
    };
    $('models').appendChild(li);
  });
}
function gpuName() {
  const gl = renderer.getContext();
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
}
// Avec le portail (app.py), les mesures sont rangées dans results/<scène>/ et apparaissent dans « Résultats ».
async function saveToServer(data) {
  const src = models[0]?.url || '';
  const m = src.match(/results\/([^/]+)\//) || src.match(/data\/([^/]+?)(\.[^./]+)+$/);
  const scene = m ? m[1] : 'benchmarks';
  try {
    const r = await fetch(`/api/bench?scene=${encodeURIComponent(scene)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    });
    if (r.ok) log(`Enregistré dans ${(await r.json()).path} (onglet Résultats du portail).`);
  } catch { /* visualiseur utilisé sans le portail : seul le téléchargement est possible */ }
}

function download(name, obj) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' }));
  a.download = name; a.click();
}

$('files').onchange = (e) => {
  for (const f of e.target.files) models.push({ name: f.name, file: f });
  renderModels();
};
$('addUrls').onclick = () => {
  for (const u of $('urls').value.split('\n').map((s) => s.trim()).filter(Boolean)) models.push({ name: u.split('/').pop(), url: u });
  renderModels();
};
$('clearModels').onclick = () => { models = []; renderModels(); };
$('addPose').onclick = () => { poses.push(currentPose()); updatePoseCount(); };
$('orbitPoses').onclick = () => { poses = orbitPoses(8); updatePoseCount(); };
$('clearPoses').onclick = () => { poses = []; updatePoseCount(); };
$('exportPoses').onclick = () => download('poses.json', poses);
$('importPoses').onchange = async (e) => {
  poses = JSON.parse(await e.target.files[0].text()); updatePoseCount();
  if (poses.length) applyPose(poses[0]);
};
$('run').onclick = benchmark;
$('download').onclick = () => download(`bench_${Date.now()}.json`, lastResults);
$('up').onchange = setUp;
$('res').onchange = setResolution;
window.addEventListener('resize', () => { if ($('res').value === 'auto') setResolution(); });

// Paramètres d'URL : ?models=a.ply,b.ply&poses=poses.json
const params = new URLSearchParams(location.search);
if (params.get('models')) {
  for (const u of params.get('models').split(',')) models.push({ name: u.split('/').pop(), url: u });
  renderModels();
}
if (params.get('poses')) {
  fetch(params.get('poses')).then((r) => r.json()).then((p) => { poses = p; updatePoseCount(); applyPose(poses[0]); });
}
setUp();
setResolution();
if (models.length) {  // affiche directement le premier modèle demandé
  initialLoad = loadModel(models[0]);
  initialLoad.then((r) => log(`${r.name} : ${r.splatCount} gaussiennes, ${fmt(r.totalMs, 0)} ms`))
    .catch((e) => log('Erreur : ' + e.message));
}
window.bench = { benchmark, loadModel, get poses() { return poses; }, get results() { return lastResults; } };
