// Métriques de qualité image (référence = rendu du modèle original sous la même pose).
// Les images sont des RGBA Uint8ClampedArray (ImageData.data) de même taille.

export function psnr(a, b) {
  let se = 0;
  let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      const d = a[i + c] - b[i + c];
      se += d * d;
    }
    n += 3;
  }
  const mse = se / n;
  return mse === 0 ? Infinity : 10 * Math.log10((255 * 255) / mse);
}

// Noyau gaussien 11 taps, sigma = 1.5 (Wang et al. 2004).
const KERNEL = (() => {
  const k = [];
  let s = 0;
  for (let i = -5; i <= 5; i++) {
    const v = Math.exp(-(i * i) / (2 * 1.5 * 1.5));
    k.push(v);
    s += v;
  }
  return Float32Array.from(k, (v) => v / s);
})();

function blur(src, w, h) {
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      let acc = 0;
      for (let k = -5; k <= 5; k++) {
        const xx = Math.min(w - 1, Math.max(0, x + k));
        acc += KERNEL[k + 5] * src[row + xx];
      }
      tmp[row + x] = acc;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let acc = 0;
      for (let k = -5; k <= 5; k++) {
        const yy = Math.min(h - 1, Math.max(0, y + k));
        acc += KERNEL[k + 5] * tmp[yy * w + x];
      }
      out[y * w + x] = acc;
    }
  }
  return out;
}

// SSIM moyen sur les 3 canaux (fenêtre gaussienne 11x11, sigma 1.5, K1=0.01, K2=0.03).
export function ssim(a, b, w, h) {
  const C1 = (0.01 * 255) ** 2;
  const C2 = (0.03 * 255) ** 2;
  const n = w * h;
  let total = 0;
  for (let c = 0; c < 3; c++) {
    const x = new Float32Array(n);
    const y = new Float32Array(n);
    const xx = new Float32Array(n);
    const yy = new Float32Array(n);
    const xy = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const u = a[4 * i + c];
      const v = b[4 * i + c];
      x[i] = u; y[i] = v; xx[i] = u * u; yy[i] = v * v; xy[i] = u * v;
    }
    const mx = blur(x, w, h), my = blur(y, w, h);
    const sxx = blur(xx, w, h), syy = blur(yy, w, h), sxy = blur(xy, w, h);
    let acc = 0;
    let cnt = 0;
    for (let py = 5; py < h - 5; py++) {
      for (let px = 5; px < w - 5; px++) {
        const i = py * w + px;
        const vx = sxx[i] - mx[i] * mx[i];
        const vy = syy[i] - my[i] * my[i];
        const cxy = sxy[i] - mx[i] * my[i];
        acc += ((2 * mx[i] * my[i] + C1) * (2 * cxy + C2)) /
               ((mx[i] * mx[i] + my[i] * my[i] + C1) * (vx + vy + C2));
        cnt++;
      }
    }
    total += acc / cnt;
  }
  return total / 3;
}

export function frameStats(dts) {
  if (!dts.length) return {};
  const s = [...dts].sort((p, q) => p - q);
  const mean = s.reduce((p, q) => p + q, 0) / s.length;
  const q = (f) => s[Math.min(s.length - 1, Math.floor(f * s.length))];
  const worst = s.slice(Math.floor(0.99 * s.length));
  const worstMean = worst.reduce((p, v) => p + v, 0) / worst.length;
  return {
    frames: s.length,
    fpsMean: 1000 / mean,
    msMedian: q(0.5),
    msP95: q(0.95),
    msP99: q(0.99),
    fpsLow1: 1000 / worstMean,
  };
}
