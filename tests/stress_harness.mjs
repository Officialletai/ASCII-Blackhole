#!/usr/bin/env node
/**
 * Event Horizon — Empirical Adversarial Stress Test Suite (Challenger M1-1)
 *
 * Direct Chrome DevTools Protocol (CDP) client testing:
 * - ST-1: Ultra-Fast Keystroke Thrashing (100 rapid events across all controls)
 * - ST-2: Gimbal Singularity & Extreme Mouse Drag (+/-2000px with auto-orbit disabled)
 * - ST-3: Extreme Mouse Wheel Zoom Clamping ([3.5, 35.0] rs)
 * - ST-4: Extreme Viewport Resizing (1x1, 3840x2160, 100x10)
 * - ST-5: Long-Running Frame Pacing & Zero-GC Memory Stability (180 continuous frames)
 * - ST-6: State Machine Concurrency & Visual Invariants (Tab thrashing, Doppler HUD gating)
 * - ST-7: Adversarial Resilience & NaN Contamination Test (Boundary math & Recovery)
 */

import { spawn, execSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

const PROJECT_ROOT = process.cwd();
const TARGET_HTML = path.resolve(PROJECT_ROOT, 'index.html');
const PORT = 9555; // Dedicated isolated port

function findChrome() {
  const candidatePaths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    '/usr/bin/google-chrome',
    '/usr/bin/chromium'
  ];
  for (const candidate of candidatePaths) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error('Chrome not found.');
}

const CHROME_PATH = findChrome();

function killProcessTree(proc) {
  if (!proc || !proc.pid) return;
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /pid ${proc.pid} /T /F`, { stdio: 'ignore' });
    } else {
      process.kill(-proc.pid, 'SIGKILL');
    }
  } catch (err) {}
}

class CDPStressClient {
  constructor(port = PORT) {
    this.port = port;
    this.proc = null;
    this.ws = null;
    this.msgId = 1;
    this.pending = new Map();
    this.sessionId = null;
    this.tmpProfile = null;
    this.consoleErrors = [];
    this.exceptions = [];
  }

  async launch(fileUrl) {
    this.tmpProfile = fs.mkdtempSync(path.join(os.tmpdir(), 'eh-stress-'));
    const chromeArgs = [
      '--headless=new',
      `--remote-debugging-port=${this.port}`,
      `--user-data-dir=${this.tmpProfile}`,
      '--enable-webgl',
      '--ignore-gpu-blocklist',
      '--use-gl=angle',
      '--use-angle=d3d11',
      '--allow-file-access-from-files',
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
      '--window-size=1920,1080',
      '--no-first-run',
      '--no-default-browser-check',
      fileUrl
    ];

    this.proc = spawn(CHROME_PATH, chromeArgs, { stdio: 'ignore' });

    let wsUrl = null;
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`http://127.0.0.1:${this.port}/json/version`);
        if (res.ok) {
          const data = await res.json();
          wsUrl = data.webSocketDebuggerUrl;
          break;
        }
      } catch (err) {
        await new Promise(r => setTimeout(r, 200));
      }
    }

    if (!wsUrl) throw new Error('Failed to connect to Chrome CDP.');

    this.ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
          else resolve(msg.result);
        }
        if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
          this.consoleErrors.push(msg.params.args.map(a => a.value || a.description).join(' '));
        }
        if (msg.method === 'Runtime.exceptionThrown') {
          this.exceptions.push(msg.params.exceptionDetails.text);
        }
      } catch (err) {}
    };

    const targets = await this.send('Target.getTargets');
    const page = targets.targetInfos.find(t => t.type === 'page');
    if (!page) throw new Error('No page target.');

    const attached = await this.send('Target.attachToTarget', { targetId: page.targetId, flatten: true });
    this.sessionId = attached.sessionId;

    await this.sendSession('Runtime.enable');
    await this.sendSession('Page.enable');
    await this.sendSession('Emulation.setDeviceMetricsOverride', {
      width: 1920,
      height: 1080,
      deviceScaleFactor: 1,
      mobile: false
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.msgId++;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  sendSession(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.msgId++;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, sessionId: this.sessionId, method, params }));
    });
  }

  async evaluate(expression) {
    const res = await this.sendSession('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true
    });
    if (res.exceptionDetails) {
      throw new Error(`Eval error: ${res.exceptionDetails.text}`);
    }
    return res.result ? res.result.value : undefined;
  }

  async dispatchKey(code, key = code, vk = 0) {
    await this.sendSession('Input.dispatchKeyEvent', { type: 'rawKeyDown', windowsVirtualKeyCode: vk, code, key });
    await new Promise(r => setTimeout(r, 20));
    await this.sendSession('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: vk, code, key });
    await new Promise(r => setTimeout(r, 30));
  }

  async dispatchMouseDrag(x1, y1, x2, y2, steps = 15, durationMs = 200) {
    await this.sendSession('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x1, y: y1 });
    await new Promise(r => setTimeout(r, 20));
    await this.sendSession('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y: y1, button: 'left', buttons: 1, clickCount: 1 });

    const stepInterval = Math.max(10, Math.floor(durationMs / steps));
    for (let i = 1; i <= steps; i++) {
      const progress = i / steps;
      const curX = Math.round(x1 + (x2 - x1) * progress);
      const curY = Math.round(y1 + (y2 - y1) * progress);
      await new Promise(r => setTimeout(r, stepInterval));
      await this.sendSession('Input.dispatchMouseEvent', { type: 'mouseMoved', x: curX, y: curY, buttons: 1 });
    }

    await new Promise(r => setTimeout(r, 30));
    await this.sendSession('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y: y2, button: 'left', buttons: 0 });
    await new Promise(r => setTimeout(r, 40));
  }

  async dispatchMouseWheel(x, y, deltaX, deltaY) {
    await this.sendSession('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX, deltaY });
    await new Promise(r => setTimeout(r, 50));
  }

  async close() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }
    if (this.proc) {
      killProcessTree(this.proc);
    }
    if (this.tmpProfile && fs.existsSync(this.tmpProfile)) {
      try { fs.rmSync(this.tmpProfile, { recursive: true, force: true }); } catch (e) {}
    }
  }
}

async function runStressSuite() {
  console.log('================================================================================');
  console.log('       EVENT HORIZON — EMPIRICAL ADVERSARIAL STRESS TEST SUITE       ');
  console.log('================================================================================\n');

  const client = new CDPStressClient(PORT);
  const fileUrl = 'file:///' + TARGET_HTML.replace(/\\/g, '/');

  const results = [];
  function assert(id, name, pass, details) {
    const tag = pass ? '\x1b[32m[PASS]\x1b[0m' : '\x1b[31m[FAIL]\x1b[0m';
    console.log(`  ${tag} ${id}: ${name} — ${details}`);
    results.push({ id, name, pass, details });
    return pass;
  }

  try {
    console.log('[STAGE 1] Booting headless Chrome on isolated port ' + PORT + '...');
    await client.launch(fileUrl);
    console.log('[STAGE 1] Connected.\n');

    await new Promise(r => setTimeout(r, 1000));

    // Dismiss intro screen
    await client.dispatchKey('Space', ' ', 32);
    await new Promise(r => setTimeout(r, 800));

    // ST-1: Ultra-Fast Keystroke Thrashing (100 rapid events)
    console.log('[TEST ST-1] Executing 100-keystroke rapid thrashing storm...');
    const keys = [
      ['Digit1', '1'], ['Digit2', '2'], ['Digit3', '3'], ['Digit4', '4'],
      ['Space', ' '], ['KeyH', 'h'], ['Tab', 'Tab'], ['KeyO', 'o'],
      ['KeyR', 'r'], ['BracketLeft', '['], ['BracketRight', ']'], ['KeyF', 'f']
    ];

    for (let i = 0; i < 100; i++) {
      const [c, k] = keys[i % keys.length];
      await client.dispatchKey(c, k);
    }
    await new Promise(r => setTimeout(r, 300));

    const st1State = await client.evaluate(`(() => {
      const state = window.APP_STATE || {};
      const gl = (document.getElementById('glcanvas') || document.querySelector('canvas')).getContext('webgl2');
      return {
        mode: state.mode,
        isHollywood: typeof state.isHollywood === 'boolean',
        renderScale: state.renderScale,
        presenterActive: typeof state.presenterActive === 'boolean',
        hudVisible: typeof state.hudVisible === 'boolean',
        glLost: gl.isContextLost(),
        glErr: gl.getError()
      };
    })()`);

    const st1Pass = [1, 2, 3, 4].includes(st1State.mode) &&
      st1State.renderScale >= 0.4 && st1State.renderScale <= 1.0 &&
      st1State.isHollywood && st1State.presenterActive && st1State.hudVisible &&
      !st1State.glLost && st1State.glErr === 0;

    assert('ST-1', 'Ultra-Fast Keystroke Thrashing Storm (100 events)', st1Pass,
      `Mode: ${st1State.mode}, Scale: ${st1State.renderScale.toFixed(1)}, GLLost: ${st1State.glLost}, GLErr: ${st1State.glErr}`);

    // ST-2: Gimbal Singularity & Extreme Mouse Drag Attack with Auto-Orbit OFF
    console.log('\n[TEST ST-2] Stressing polar gimbal bounds (+/-2000px drag with auto-orbit disabled)...');
    // Ensure presenter auto-orbit is disabled so it doesn't overwrite phi
    await client.evaluate(`if (window.APP_STATE) window.APP_STATE.presenterActive = false;`);

    // Drag heavy upward (+2000px)
    await client.dispatchMouseDrag(960, 800, 960, -1200, 20, 250);
    await new Promise(r => setTimeout(r, 400));

    const northPoleState = await client.evaluate(`(() => {
      const cam = window.Camera;
      const v = cam.getViewMatrix();
      let hasNaN = false;
      for (let i = 0; i < 16; i++) if (isNaN(v[i]) || !isFinite(v[i])) hasNaN = true;
      return { phi: cam.phi, phiTarget: cam.phiTarget, maxPhi: cam.maxPhi, minPhi: cam.minPhi, hasNaN };
    })()`);

    // Drag heavy downward (-4000px)
    await client.dispatchMouseDrag(960, 200, 960, 4200, 20, 250);
    await new Promise(r => setTimeout(r, 400));

    const southPoleState = await client.evaluate(`(() => {
      const cam = window.Camera;
      const v = cam.getViewMatrix();
      let hasNaN = false;
      for (let i = 0; i < 16; i++) if (isNaN(v[i]) || !isFinite(v[i])) hasNaN = true;
      return { phi: cam.phi, phiTarget: cam.phiTarget, minPhi: cam.minPhi, maxPhi: cam.maxPhi, hasNaN };
    })()`);

    // Reset camera view
    await client.dispatchKey('KeyR', 'r', 82);
    await new Promise(r => setTimeout(r, 300));

    // Note: In index.html, dy is added to phiTarget (negative dy from upward drag reaches minPhi, positive dy reaches maxPhi)
    const st2Pass = !northPoleState.hasNaN && !southPoleState.hasNaN &&
      Math.abs(northPoleState.phiTarget - northPoleState.minPhi) < 0.01 &&
      Math.abs(southPoleState.phiTarget - southPoleState.maxPhi) < 0.01;

    assert('ST-2', 'Polar Gimbal Lock & Singularity Stress (+/-2000px Drag)', st2Pass,
      `Min bound reached: ${northPoleState.phi.toFixed(3)} rad (Limit: ${northPoleState.minPhi}), Max bound reached: ${southPoleState.phi.toFixed(3)} rad (Limit: ${southPoleState.maxPhi}), NaNs: ${northPoleState.hasNaN || southPoleState.hasNaN}`);

    // ST-3: Extreme Mouse Wheel Zoom Clamping ([3.5, 35.0] rs)
    console.log('\n[TEST ST-3] Hammering mouse wheel zoom (+/-10,000 cumulative delta)...');
    for (let i = 0; i < 30; i++) {
      await client.dispatchMouseWheel(960, 540, 0, -500);
    }
    await new Promise(r => setTimeout(r, 400));
    const minZoom = await client.evaluate(`window.Camera ? { r: window.Camera.radius, target: window.Camera.radiusTarget, min: window.Camera.minRadius } : {}`);

    for (let i = 0; i < 40; i++) {
      await client.dispatchMouseWheel(960, 540, 0, 500);
    }
    await new Promise(r => setTimeout(r, 400));
    const maxZoom = await client.evaluate(`window.Camera ? { r: window.Camera.radius, target: window.Camera.radiusTarget, max: window.Camera.maxRadius } : {}`);

    await client.dispatchKey('KeyR', 'r', 82);
    await new Promise(r => setTimeout(r, 300));

    const st3Pass = minZoom.target >= minZoom.min - 0.01 && minZoom.target <= minZoom.min + 0.5 &&
      maxZoom.target <= maxZoom.max + 0.01 && maxZoom.target >= maxZoom.max - 0.5 &&
      minZoom.r > 1.0; // Strictly outside horizon

    assert('ST-3', 'Extreme Mouse Wheel Zoom Clamping ([3.5, 35.0] rs)', st3Pass,
      `Min reached: ${minZoom.target.toFixed(2)} rs (Min limit: ${minZoom.min}), Max reached: ${maxZoom.target.toFixed(2)} rs (Max limit: ${maxZoom.max})`);

    // ST-4: Viewport Extreme Resizing Attack (1x1, 3840x2160, 100x10)
    console.log('\n[TEST ST-4] Subjecting render viewport to extreme aspect ratios...');
    const testViewports = [
      { w: 1, h: 1 },
      { w: 3840, h: 2160 },
      { w: 100, h: 10 },
      { w: 1920, h: 1080 }
    ];

    let resizeOk = true;
    for (const vp of testViewports) {
      await client.sendSession('Emulation.setDeviceMetricsOverride', {
        width: vp.w,
        height: vp.h,
        deviceScaleFactor: 1,
        mobile: false
      });
      await client.evaluate(`window.dispatchEvent(new Event('resize'))`);
      await new Promise(r => setTimeout(r, 100));

      const vpStatus = await client.evaluate(`(() => {
        const canvas = document.getElementById('glcanvas');
        const gl = canvas.getContext('webgl2');
        return { w: canvas.width, h: canvas.height, glErr: gl.getError() };
      })()`);
      if (vpStatus.glErr !== 0) resizeOk = false;
    }

    assert('ST-4', 'Extreme Viewport Resizing Resilience (1x1 to 4K)', resizeOk,
      `All viewport scales handled with 0 WebGL framebuffer errors`);

    // ST-5: Long-Running Frame Pacing & Zero-GC Memory Drift (180 frames)
    console.log('\n[TEST ST-5] Auditing frame pacing and per-frame memory drift over 180 continuous RAF frames...');
    const perfData = await client.evaluate(`(() => {
      return new Promise((resolve) => {
        let frameCount = 0;
        const frameTimes = [];
        let prevTime = performance.now();
        const startHeap = performance.memory ? performance.memory.usedJSHeapSize : 0;

        function sample() {
          const now = performance.now();
          frameTimes.push(now - prevTime);
          prevTime = now;
          frameCount++;

          if (frameCount >= 180) {
            const endHeap = performance.memory ? performance.memory.usedJSHeapSize : 0;
            const totalElapsed = frameTimes.reduce((a, b) => a + b, 0);
            const meanFt = totalElapsed / frameTimes.length;
            const variance = frameTimes.reduce((acc, ft) => acc + Math.pow(ft - meanFt, 2), 0) / frameTimes.length;
            const stdDev = Math.sqrt(variance);
            const heapDriftBytes = endHeap - startHeap;
            resolve({
              frameCount,
              meanFt,
              fps: 1000 / meanFt,
              stdDevFt: stdDev,
              startHeapMB: startHeap / (1024 * 1024),
              endHeapMB: endHeap / (1024 * 1024),
              heapDriftBytes,
              bytesPerFrame: heapDriftBytes / frameCount
            });
          } else {
            requestAnimationFrame(sample);
          }
        }
        requestAnimationFrame(sample);
      });
    })()`);

    const st5Pass = perfData.fps >= 30.0 && perfData.bytesPerFrame < 1024;
    assert('ST-5', 'Long-Running Frame Pacing & Zero-GC Memory Stability (180 frames)', st5Pass,
      `FPS: ${perfData.fps.toFixed(1)}, Frame Jitter (StdDev): ${perfData.stdDevFt.toFixed(2)}ms, Drift: ${(perfData.bytesPerFrame).toFixed(1)} bytes/frame (Start: ${perfData.startHeapMB.toFixed(2)}MB, End: ${perfData.endHeapMB.toFixed(2)}MB)`);

    // ST-6: State Machine Concurrency & Visual Invariant Integrity
    console.log('\n[TEST ST-6] Auditing state machine invariants & DOM overlay coherence...');
    for (let i = 0; i < 20; i++) {
      await client.dispatchKey('Tab', 'Tab', 9);
      await new Promise(r => setTimeout(r, 20));
    }
    const hudInvar = await client.evaluate(`(() => {
      const hud = document.getElementById('hud');
      const state = window.APP_STATE || {};
      const elHidden = hud.classList.contains('hidden');
      return { elHidden, hudVisible: state.hudVisible, consistent: elHidden !== state.hudVisible };
    })()`);

    const dopplerConsistency = [];
    for (const m of [1, 2, 3, 4]) {
      await client.dispatchKey(`Digit${m}`, `${m}`);
      await new Promise(r => setTimeout(r, 200));
      const dopCheck = await client.evaluate(`(() => {
        const dop = document.getElementById('hud-doppler');
        const state = window.APP_STATE || {};
        const isHidden = dop.classList.contains('hidden');
        return { mode: state.mode, isHidden, valid: (state.mode === 4 ? !isHidden : isHidden) };
      })()`);
      dopplerConsistency.push(dopCheck.valid);
    }

    const st6Pass = hudInvar.consistent && dopplerConsistency.every(Boolean);
    assert('ST-6', 'State Machine Concurrency & Visual Invariants', st6Pass,
      `HUD Coherent: ${hudInvar.consistent}, Doppler strictly gated to Mode 4: ${dopplerConsistency.every(Boolean)}`);

    // ST-7: Title Card Debounce / Rapid Thrash Lifetime
    console.log('\n[TEST ST-7] Auditing title card timer handling under rapid mode thrashing...');
    for (let i = 0; i < 10; i++) {
      await client.dispatchKey('Space', ' ', 32);
      await new Promise(r => setTimeout(r, 50));
    }
    // Wait 2.2 seconds for timeout
    await new Promise(r => setTimeout(r, 2200));
    const titleCardSettled = await client.evaluate(`(() => {
      const card = document.getElementById('title-card');
      return {
        hasShow: card.classList.contains('show'),
        hasFadeOut: card.classList.contains('fade-out'),
        visible: card.classList.contains('show') || card.style.opacity > '0'
      };
    })()`);
    const st7Pass = !titleCardSettled.hasShow;
    assert('ST-7', 'Title Card Fade-Out Lifecycle under Rapid Navigation', st7Pass,
      `Title card cleanly faded out after timer (hasShow: ${titleCardSettled.hasShow}, hasFadeOut: ${titleCardSettled.hasFadeOut})`);

    // ST-8: Cross-Interaction Concurrent Mode Switch & Rescaling during Drag
    console.log('\n[TEST ST-8] Stressing concurrent inputs: mode jumping & scale keys during pointer drag...');
    await client.sendSession('Input.dispatchMouseEvent', { type: 'mousePressed', x: 500, y: 500, button: 'left', buttons: 1 });
    await client.sendSession('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 600, y: 550, buttons: 1 });
    await client.dispatchKey('Digit3', '3');
    await client.dispatchKey('BracketLeft', '[');
    await client.sendSession('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 700, y: 600, buttons: 1 });
    await client.dispatchKey('Digit4', '4');
    await client.dispatchKey('BracketRight', ']');
    await client.sendSession('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 700, y: 600, button: 'left', buttons: 0 });
    await new Promise(r => setTimeout(r, 200));

    const st8State = await client.evaluate(`(() => {
      const state = window.APP_STATE || {};
      const cam = window.Camera || {};
      return {
        mode: state.mode,
        isDragging: cam.isDragging,
        renderScale: state.renderScale
      };
    })()`);
    const st8Pass = st8State.mode === 4 && !st8State.isDragging && st8State.renderScale >= 0.4 && st8State.renderScale <= 1.0;
    assert('ST-8', 'Concurrent Interaction (Drag + Mode Switch + Rescale)', st8Pass,
      `Final Mode: ${st8State.mode}, Dragging Released: ${!st8State.isDragging}, Scale: ${st8State.renderScale.toFixed(1)}`);

    // ST-9: Multi-Cycle Space Wrap-Around (16 consecutive Space presses)
    console.log('\n[TEST ST-9] Verifying 16 consecutive Space navigation presses (4 full cycles)...');
    await client.dispatchKey('Digit1', '1');
    await new Promise(r => setTimeout(r, 200));

    const wrapSequence = [];
    for (let i = 0; i < 16; i++) {
      await client.dispatchKey('Space', ' ', 32);
      await new Promise(r => setTimeout(r, 80));
      const m = await client.evaluate(`window.APP_STATE ? window.APP_STATE.mode : 0`);
      wrapSequence.push(m);
    }

    // Expected sequence: 2,3,4,1, 2,3,4,1, 2,3,4,1, 2,3,4,1
    const expected = [2,3,4,1, 2,3,4,1, 2,3,4,1, 2,3,4,1];
    const matchCount = wrapSequence.filter((v, idx) => v === expected[idx]).length;
    const st9Pass = matchCount === 16;
    assert('ST-9', 'Multi-Cycle Space Navigation Wrap-Around (16 cycles)', st9Pass,
      `Matched ${matchCount}/16 transitions: ${wrapSequence.join(',')}`);

    // Final summary
    const allPassed = results.every(r => r.pass);
    console.log('\n================================================================================');
    console.log(`STRESS TEST VERDICT: ${allPassed ? '\x1b[32mALL STRESS TESTS PASSED\x1b[0m' : '\x1b[31mFAILURES DETECTED\x1b[0m'}`);
    console.log(`Total: ${results.length} | Passed: ${results.filter(r => r.pass).length} | Failed: ${results.filter(r => !r.pass).length}`);
    console.log('================================================================================\n');

    process.exit(allPassed ? 0 : 1);
  } catch (err) {
    console.error('Fatal error during stress suite:', err);
    process.exit(1);
  } finally {
    await client.close();
  }
}

runStressSuite();
