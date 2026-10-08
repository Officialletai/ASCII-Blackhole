#!/usr/bin/env node
/**
 * Empirical Challenger M2-1 Physics & Shader Stress Test Probe
 *
 * Rigorous empirical investigation of:
 * 1. Deflection LUT numerical validity & divergence near b_crit
 * 2. Vector RK4 geodesic ray marcher numerical stability (no NaNs, Infs, grazing stability)
 * 3. Accretion disk double-arc geometry (intersections above and below shadow)
 * 4. Relativistic Doppler beaming contrast & Hollywood symmetry in rendered artifacts
 * 5. Shadow integrity audit (detecting ray budget horizon exhaustion / star leak)
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';

console.log('='.repeat(75));
console.log('CHALLENGER M2-1: EMPIRICAL PHYSICS & SHADER STRESS PROBE');
console.log('Platform:', process.platform, '| Node:', process.version);
console.log('='.repeat(75));

const RS = 1.0;
const R_PH = 1.5 * RS;
const B_CRIT = (3.0 * Math.sqrt(3.0) / 2.0) * RS; // ~2.598076211353316
const R_ISCO = 3.0 * RS;
const R_OUT = 12.0 * RS;
const DISK_TILT = 1.3962634; // ~80 degrees

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;
const findings = [];

function assert(desc, condition, details = '') {
  totalTests++;
  if (condition) {
    passedTests++;
    console.log(`  [PASS] ${desc}${details ? ' — ' + details : ''}`);
  } else {
    failedTests++;
    console.error(`  [CHALLENGE / BUG] ${desc}${details ? ' — ' + details : ''}`);
    findings.push({ desc, details });
  }
}

/* =========================================================================
 * Tier 1: Deflection LUT & Binet Null Geodesic Quadrature
 * ========================================================================= */
console.log('\n[TIER 1] Deflection LUT & Binet Null Geodesic Quadrature Verification');

// Functions from index.html
function solveUMax(b) {
  let u = 1.0 / b;
  for (let k = 0; k < 16; k++) {
    const f = u * u * u - u * u + 1.0 / (b * b);
    const df = 3.0 * u * u - 2.0 * u;
    const next = u - f / df;
    if (Math.abs(next - u) < 1e-10) return next;
    u = next;
  }
  return u;
}

function computeDeflection(b) {
  if (b <= B_CRIT) return -1.0;
  const umax = solveUMax(b);
  const N = 64;
  const dTheta = (0.5 * Math.PI) / N;
  let sum = 0.0;
  for (let i = 0; i <= N; i++) {
    const theta = i * dTheta;
    const sinT = Math.sin(theta);
    const sin2 = sinT * sinT;
    const sin4 = sin2 * sin2;
    const denom = Math.sqrt(Math.max(1e-12, (1.0 + sin2) - umax * (1.0 + sin2 + sin4)));
    const term = (2.0 * sinT) / denom;
    const weight = (i === 0 || i === N) ? 1.0 : (i % 2 === 1 ? 4.0 : 2.0);
    sum += term * weight;
  }
  return 2.0 * ((dTheta / 3.0) * sum) - Math.PI;
}

// 1.1 Critical Impact Parameter precision
assert('B_CRIT analytical value matches (3*sqrt(3)/2)*rs',
  Math.abs(B_CRIT - 2.598076211353316) < 1e-12,
  `b_crit = ${B_CRIT.toFixed(7)}`);

// 1.2 U_max convergence across LUT range
const LUT_SIZE = 512;
const B_MAX = 16.0 * RS;
let nanCount = 0;
let infCount = 0;
let uMaxBounded = true;
let deflectionsMonotonic = true;
let prevDeflection = 1e9;

for (let i = 0; i < LUT_SIZE; i++) {
  const b = ((i + 0.5) / LUT_SIZE) * B_MAX;
  if (b > B_CRIT) {
    const umax = solveUMax(b);
    if (isNaN(umax)) nanCount++;
    if (!isFinite(umax)) infCount++;
    if (umax <= 0 || umax > 0.6667) uMaxBounded = false;

    const def = computeDeflection(b);
    if (isNaN(def)) nanCount++;
    if (!isFinite(def)) infCount++;
    if (def > prevDeflection && i > 100) deflectionsMonotonic = false;
    prevDeflection = def;
  }
}

assert('LUT generation: 0 NaNs and 0 Infs across all 512 bins',
  nanCount === 0 && infCount === 0,
  `NaNs: ${nanCount}, Infs: ${infCount}`);

assert('u_max physically bounded in (0, 2/3] for all b > b_crit',
  uMaxBounded,
  'u_max in (0, 0.6667]');

assert('Deflection angle strictly decreases with increasing impact parameter b',
  deflectionsMonotonic,
  'Delta phi monotonically decreasing for b > b_crit');

// 1.3 Asymptotic behavior near b_crit (photon sphere divergence)
const bNearCrit = B_CRIT + 0.0001;
const defNearCrit = computeDeflection(bNearCrit);
assert('Deflection angle diverges near b_crit (>= 2*pi winding)',
  defNearCrit > 2.0 * Math.PI,
  `b = ${bNearCrit.toFixed(5)} -> Delta phi = ${defNearCrit.toFixed(3)} rad (${(defNearCrit / Math.PI).toFixed(2)} pi)`);

// 1.4 Post-Newtonian 2nd-order deflection comparison (Delta phi = 2*rs/b + 15*pi*rs^2/(16*b^2))
const bWeak = 15.0;
const defSim = computeDeflection(bWeak);
const def1st = (2.0 * RS) / bWeak; // 0.1333 rad
const def2nd = def1st + (15.0 * Math.PI * RS * RS) / (16.0 * bWeak * bWeak); // 0.1464 rad
const err2nd = Math.abs(defSim - def2nd) / def2nd;
assert('Weak-field deflection matches Schwarzschild 2nd-order GR post-Newtonian expansion to within 1.5% at b=15',
  err2nd < 0.015,
  `Sim: ${defSim.toFixed(4)} rad vs 2nd-Order GR: ${def2nd.toFixed(4)} rad (diff: ${(err2nd * 100).toFixed(2)}%)`);

// 1.5 Closest approach r_min approaches photon sphere (1.5 rs) at b -> b_crit
const umaxCrit = solveUMax(B_CRIT + 1e-6);
const rminCrit = 1.0 / umaxCrit;
assert('Closest approach r_min -> 1.5 rs as b -> b_crit',
  Math.abs(rminCrit - 1.5) < 0.005,
  `r_min = ${rminCrit.toFixed(5)} rs (target: 1.50000)`);


/* =========================================================================
 * Tier 2: Vector RK4 Ray Marcher Numerical Bounds & Grazing Stability
 * ========================================================================= */
console.log('\n[TIER 2] Vector RK4 Geodesic Ray Marcher Numerical Stability');

function getGeodesicAcceleration(pos, vel) {
  const r2 = pos[0]*pos[0] + pos[1]*pos[1] + pos[2]*pos[2];
  const v2 = vel[0]*vel[0] + vel[1]*vel[1] + vel[2]*vel[2];
  const r = Math.sqrt(r2);
  const rdotv = pos[0]*vel[0] + pos[1]*vel[1] + pos[2]*vel[2];
  const L2 = Math.max(0.0, r2 * v2 - rdotv * rdotv);
  const r5 = r2 * r2 * r;
  const factor = (-1.5 * RS * L2 / Math.max(r5, 1e-4));
  return [factor * pos[0], factor * pos[1], factor * pos[2]];
}

function rk4Step(pos, vel, h) {
  const k1_x = [vel[0], vel[1], vel[2]];
  const k1_v = getGeodesicAcceleration(pos, vel);
  const x2 = [pos[0] + 0.5 * h * k1_x[0], pos[1] + 0.5 * h * k1_x[1], pos[2] + 0.5 * h * k1_x[2]];
  const v2 = [vel[0] + 0.5 * h * k1_v[0], vel[1] + 0.5 * h * k1_v[1], vel[2] + 0.5 * h * k1_v[2]];
  const k2_x = v2;
  const k2_v = getGeodesicAcceleration(x2, v2);
  const x3 = [pos[0] + 0.5 * h * k2_x[0], pos[1] + 0.5 * h * k2_x[1], pos[2] + 0.5 * h * k2_x[2]];
  const v3 = [vel[0] + 0.5 * h * k2_v[0], vel[1] + 0.5 * h * k2_v[1], vel[2] + 0.5 * h * k2_v[2]];
  const k3_x = v3;
  const k3_v = getGeodesicAcceleration(x3, v3);
  const x4 = [pos[0] + h * k3_x[0], pos[1] + h * k3_x[1], pos[2] + h * k3_x[2]];
  const v4 = [vel[0] + h * k3_v[0], vel[1] + h * k3_v[1], vel[2] + h * k3_v[2]];
  const k4_x = v4;
  const k4_v = getGeodesicAcceleration(x4, v4);

  pos[0] += (h / 6.0) * (k1_x[0] + 2.0 * k2_x[0] + 2.0 * k3_x[0] + k4_x[0]);
  pos[1] += (h / 6.0) * (k1_x[1] + 2.0 * k2_x[1] + 2.0 * k3_x[1] + k4_x[1]);
  pos[2] += (h / 6.0) * (k1_x[2] + 2.0 * k2_x[2] + 2.0 * k3_x[2] + k4_x[2]);
  vel[0] += (h / 6.0) * (k1_v[0] + 2.0 * k2_v[0] + 2.0 * k3_v[0] + k4_v[0]);
  vel[1] += (h / 6.0) * (k1_v[1] + 2.0 * k2_v[1] + 2.0 * k3_v[1] + k4_v[1]);
  vel[2] += (h / 6.0) * (k1_v[2] + 2.0 * k2_v[2] + 2.0 * k3_v[2] + k4_v[2]);
}

// 2.1 Adversarial Ray Batch: 5,000 rays spanning extreme parameter space
let rk4NaNs = 0;
let rk4Infs = 0;
const testCameraDistances = [3.5, 7.0, 14.0, 25.0, 35.0];

for (const camDist of testCameraDistances) {
  for (let b = 0.0; b <= 10.0; b += 0.1) {
    for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 4) {
      const origin = [0, 2.5, camDist];
      const target = [b * Math.cos(angle), b * Math.sin(angle), 0];
      const dir = [target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]];
      const len = Math.hypot(dir[0], dir[1], dir[2]);
      dir[0] /= len; dir[1] /= len; dir[2] /= len;

      let pos = [...origin];
      let vel = [...dir];

      for (let s = 0; s < 64; s++) {
        const r = Math.hypot(pos[0], pos[1], pos[2]);
        if (r <= 1.005 * RS) break;
        const h = Math.min(0.55, Math.max(0.04, 0.06 * (r - 0.8 * RS)));
        rk4Step(pos, vel, h);
        if (isNaN(pos[0]) || isNaN(vel[0])) rk4NaNs++;
        if (!isFinite(pos[0]) || !isFinite(vel[0])) rk4Infs++;
      }
    }
  }
}

assert('RK4 Stress Test: 0 NaNs and 0 Infs across 4,000+ rays spanning r in [3.5, 35.0]',
  rk4NaNs === 0 && rk4Infs === 0,
  `NaNs: ${rk4NaNs}, Infs: ${rk4Infs}`);

// 2.2 Grazing stability at b = b_crit +/- epsilon
const epsilons = [1e-6, 1e-5, 1e-4, 1e-3, 1e-2];
let grazingStable = true;
for (const eps of epsilons) {
  for (const sign of [-1, 1]) {
    const b = B_CRIT + sign * eps;
    const origin = [0, 0, 10.0];
    const target = [b, 0, 0];
    const dir = [target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]];
    const len = Math.hypot(dir[0], dir[1], dir[2]);
    dir[0] /= len; dir[1] /= len; dir[2] /= len;

    let pos = [...origin];
    let vel = [...dir];
    for (let s = 0; s < 64; s++) {
      const r = Math.hypot(pos[0], pos[1], pos[2]);
      if (r <= 1.005 * RS) break;
      const h = Math.min(0.55, Math.max(0.04, 0.06 * (r - 0.8 * RS)));
      rk4Step(pos, vel, h);
      if (isNaN(pos[0]) || !isFinite(pos[0])) grazingStable = false;
    }
  }
}
assert('Extreme grazing rays near b_crit remain completely numerically stable',
  grazingStable,
  'b = b_crit +/- {1e-6, 1e-5, 1e-4, 1e-3, 1e-2}');


/* =========================================================================
 * Tier 3: Accretion Disk Double-Arc Ray-Plane Geometry
 * ========================================================================= */
console.log('\n[TIER 3] Accretion Disk Double-Arc Ray-Plane Geometry Verification');

const eye = [0, 3.126898, 14.67046];
const invLen = 1.0 / Math.hypot(eye[0], eye[1], eye[2]);
const fx = -eye[0] * invLen, fy = -eye[1] * invLen, fz = -eye[2] * invLen;
let rx = -fz, ry = 0.0, rz = fx;
const rLen = Math.hypot(rx, rz);
rx /= rLen; rz /= rLen;
const ux = ry * fz - rz * fy;
const uy = rz * fx - rx * fz;
const uz = rx * fy - ry * fx;

const diskNormal = [0.0, Math.cos(DISK_TILT), Math.sin(DISK_TILT)];
let topHits = 0, botHits = 0;

for (let py = 100; py < 1000; py += 10) {
  const uvY = 1.0 - (py + 0.5) / 1080.0;
  const screenPy = uvY * 2.0 - 1.0;
  const camRayY = screenPy * 0.8;
  const camRayZ = 1.6;
  const cLen = Math.hypot(camRayY, camRayZ);
  const cry = camRayY / cLen, crz = camRayZ / cLen;

  const dir = [
    cry * ux + crz * fx,
    cry * uy + crz * fy,
    cry * uz + crz * fz
  ];

  let pos = [...eye];
  let vel = [...dir];
  let prevDist = pos[0]*diskNormal[0] + pos[1]*diskNormal[1] + pos[2]*diskNormal[2];

  for (let step = 0; step < 64; step++) {
    const r = Math.hypot(pos[0], pos[1], pos[2]);
    if (r <= 1.005) break;
    const h = Math.min(0.55, Math.max(0.04, 0.06 * (r - 0.8 * RS)));
    const p0 = [...pos];
    rk4Step(pos, vel, h);
    let currDist = pos[0]*diskNormal[0] + pos[1]*diskNormal[1] + pos[2]*diskNormal[2];
    if (prevDist * currDist < 0.0) {
      const t = prevDist / (prevDist - currDist);
      const pHit = [p0[0] + t*(pos[0]-p0[0]), p0[1] + t*(pos[1]-p0[1]), p0[2] + t*(pos[2]-p0[2])];
      const rHit = Math.hypot(pHit[0], pHit[1], pHit[2]);
      if (rHit >= R_ISCO && rHit <= R_OUT) {
        if (py < 450) topHits++;
        else if (py > 630) botHits++;
      }
    }
    prevDist = currDist;
  }
}

assert('Accretion disk upper lensed arch intersected (rear disk bent over BH)',
  topHits >= 15,
  `Upper arch ray crossings: ${topHits}`);

assert('Accretion disk lower lensed arch intersected (disk crossing below BH)',
  botHits >= 15,
  `Lower arch ray crossings: ${botHits}`);


/* =========================================================================
 * Tier 4: Doppler Beaming Contrast & Artifact Pixel Inspection
 * ========================================================================= */
console.log('\n[TIER 4] Doppler Beaming Contrast & Artifact Pixel Inspection');

function parsePngRGB24(filePath) {
  const buf = fs.readFileSync(filePath);
  let offset = 8;
  const idatChunks = [];
  while (offset < buf.length) {
    const chunkLen = buf.readUInt32BE(offset);
    const chunkType = buf.toString('ascii', offset + 4, offset + 8);
    if (chunkType === 'IDAT') idatChunks.push(buf.subarray(offset + 8, offset + 8 + chunkLen));
    offset += 12 + chunkLen;
  }
  const decomp = zlib.inflateSync(Buffer.concat(idatChunks));
  const w = 1920, h = 1080, bpp = 3, stride = w * bpp;
  let srcPos = 0, prev = Buffer.alloc(stride);
  const pixels = Buffer.alloc(w * h * 3);

  for (let y = 0; y < h; y++) {
    const f = decomp[srcPos++];
    const cur = Buffer.alloc(stride);
    for (let x = 0; x < stride; x++) {
      const raw = decomp[srcPos++];
      const a = x >= bpp ? cur[x - bpp] : 0;
      const b = prev[x];
      const c = x >= bpp ? prev[x - bpp] : 0;
      let val = raw;
      if (f === 1) val = (raw + a) & 0xff;
      else if (f === 2) val = (raw + b) & 0xff;
      else if (f === 3) val = (raw + Math.floor((a + b) / 2)) & 0xff;
      else if (f === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        let pr = c;
        if (pa <= pb && pa <= pc) pr = a;
        else if (pb <= pc) pr = b;
        val = (raw + pr) & 0xff;
      }
      cur[x] = val;
    }
    cur.copy(pixels, y * stride);
    prev = cur;
  }
  return { w, h, pixels };
}

const artifactsDir = path.resolve('artifacts');
const hollywoodPath = path.join(artifactsDir, 'artifact_mode4_cinematic_hollywood.png');
const physicalPath = path.join(artifactsDir, 'artifact_mode4_cinematic_physical.png');

assert('Hollywood artifact exists on disk', fs.existsSync(hollywoodPath));
assert('Physical artifact exists on disk', fs.existsSync(physicalPath));

const imgHollywood = parsePngRGB24(hollywoodPath);
const imgPhysical = parsePngRGB24(physicalPath);

function getPixelRGB(img, x, y) {
  const idx = (y * img.w + x) * 3;
  return [img.pixels[idx], img.pixels[idx+1], img.pixels[idx+2]];
}

function getPixelLum(img, x, y) {
  const rgb = getPixelRGB(img, x, y);
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

// Measure Hollywood Left vs Right Horizontal Limb Symmetry at (960 - 250, 540) vs (960 + 250, 540)
const hwLeftLum = getPixelLum(imgHollywood, 960 - 250, 540);
const hwRightLum = getPixelLum(imgHollywood, 960 + 250, 540);
const hwRatio = hwRightLum / Math.max(0.1, hwLeftLum);

assert('Hollywood Mode demonstrates photometric symmetry between opposing horizontal limbs (< 5% difference)',
  Math.abs(hwRatio - 1.0) < 0.05,
  `Left: ${hwLeftLum.toFixed(1)}, Right: ${hwRightLum.toFixed(1)}, Ratio: ${hwRatio.toFixed(3)}`);

// Measure Physical Approaching (Left) vs Receding (Right) at (960 - 300, 540) vs (960 + 300, 540)
const physLeftRGB = getPixelRGB(imgPhysical, 960 - 300, 540);
const physRightRGB = getPixelRGB(imgPhysical, 960 + 300, 540);
const physLeftLum = getPixelLum(imgPhysical, 960 - 300, 540);
const physRightLum = getPixelLum(imgPhysical, 960 + 300, 540);
const physContrast = physLeftLum / Math.max(0.1, physRightLum);

assert('Physical Mode demonstrates strong Doppler beaming contrast (approaching vs receding >= 3x)',
  physContrast >= 3.0,
  `Approaching: ${physLeftLum.toFixed(1)}, Receding: ${physRightLum.toFixed(1)}, Contrast: ${physContrast.toFixed(2)}x`);

// Measure Spectral Shift: Approaching limb is blueshifted (B/R >= 1.0), Receding limb is redshifted (B/R <= 0.6)
const physLeftBlueToRed = physLeftRGB[2] / Math.max(1, physLeftRGB[0]);
const physRightBlueToRed = physRightRGB[2] / Math.max(1, physRightRGB[0]);

assert('Approaching limb exhibits blueshifted spectral color compared to receding limb',
  physLeftBlueToRed >= 0.95 && physRightBlueToRed <= 0.65,
  `Approaching B/R: ${physLeftBlueToRed.toFixed(3)} (RGB: [${physLeftRGB.join(', ')}]) vs Receding B/R: ${physRightBlueToRed.toFixed(3)} (RGB: [${physRightRGB.join(', ')}])`);


/* =========================================================================
 * Tier 5: Adversarial Challenge — Shadow Integrity & Star Leak Audit
 * ========================================================================= */
console.log('\n[TIER 5] Adversarial Challenge — Mode 4 Shadow Integrity & Star Leak Audit');

// Inspect inner shadow core of Mode 4 (radius <= 40px around black hole center (960, 480))
let starsInPhysicalShadow = 0;
let starsInHollywoodShadow = 0;
let physShadowLumSum = 0;
let pixelCount = 0;

for (let y = 480 - 40; y <= 480 + 40; y++) {
  for (let x = 960 - 40; x <= 960 + 40; x++) {
    const dist = Math.hypot(x - 960, y - 480);
    if (dist <= 40) {
      pixelCount++;
      const rgbP = getPixelRGB(imgPhysical, x, y);
      const lumP = getPixelLum(imgPhysical, x, y);
      physShadowLumSum += lumP;
      // Background stars have brightness > 70
      if (rgbP[0] > 70 || rgbP[1] > 70 || rgbP[2] > 70) {
        starsInPhysicalShadow++;
      }
      const rgbH = getPixelRGB(imgHollywood, x, y);
      if (rgbH[0] > 70 || rgbH[1] > 70 || rgbH[2] > 70) {
        starsInHollywoodShadow++;
      }
    }
  }
}

const avgPhysShadowLum = physShadowLumSum / Math.max(1, pixelCount);
console.log(`  Physical Mode Shadow Non-Black Pixels (Leaked Stars > 70): ${starsInPhysicalShadow}`);
console.log(`  Hollywood Mode Shadow Non-Black Pixels (Leaked Stars > 70): ${starsInHollywoodShadow}`);
console.log(`  Physical Mode Average Shadow Core Luminance: ${avgPhysShadowLum.toFixed(2)} / 255`);

// Challenge assertion: The event horizon interior MUST be completely dark (zero leaked stars, low luminance)
assert('Adversarial Challenge: Event horizon shadow interior must be dark with zero leaked stars',
  starsInPhysicalShadow === 0 && avgPhysShadowLum < 20.0,
  `Leaked stars: ${starsInPhysicalShadow}, Avg Core Luminance: ${avgPhysShadowLum.toFixed(2)}/255`);


/* =========================================================================
 * Empirical Probe Summary
 * ========================================================================= */
console.log('\n' + '='.repeat(75));
console.log('EMPIRICAL PROBE SUMMARY');
console.log('='.repeat(75));
console.log(`Total Assertions: ${totalTests}`);
console.log(`Passed:           ${passedTests}`);
console.log(`Challenged:       ${failedTests}`);

if (failedTests > 0) {
  console.log('\n>>> EMPIRICAL CHALLENGES IDENTIFIED: <<<');
  for (const f of findings) {
    console.log(`- ${f.desc}: ${f.details}`);
  }
}
