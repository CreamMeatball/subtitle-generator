'use strict';
/**
 * Electron 메인 프로세스.
 * - BrowserWindow 생성
 * - python/engine.py 를 자식 프로세스로 띄우고 JSON-lines 프로토콜로 통신
 * - 렌더러 ↔ 엔진 사이의 브리지(IPC)
 */
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');
const readline = require('readline');

const bootstrap = require('./bootstrap');
const updater = require('./updater');

const THUMB_DIR = path.join(os.tmpdir(), 'subgen-thumbs');

let win = null;
let engine = null;
let rl = null;
let runtimeInfo = null;   // { python, engineDir, ffmpeg }

function resolveFfmpeg() {
  if (runtimeInfo && runtimeInfo.ffmpeg) return runtimeInfo.ffmpeg;
  return process.env.SUBGEN_FFMPEG || process.env.FFMPEG_PATH || 'ffmpeg';
}

function sendEvent(ev) {
  if (win && !win.isDestroyed()) {
    win.webContents.send('engine:event', ev);
  }
}

function startEngine() {
  if (engine || !runtimeInfo) return;
  const enginePath = path.join(runtimeInfo.engineDir, 'engine.py');
  const env = { ...process.env };
  if (runtimeInfo.ffmpeg) env.FFMPEG_PATH = runtimeInfo.ffmpeg;
  try {
    engine = spawn(runtimeInfo.python, ['-u', enginePath],
      { cwd: runtimeInfo.engineDir, env, windowsHide: true });
  } catch (err) {
    sendEvent({ type: 'engine_error', message: `엔진 실행 실패: ${err.message}` });
    engine = null;
    return;
  }

  engine.on('error', (err) => {
    sendEvent({
      type: 'engine_error',
      message: `python 실행 실패: ${err.message}. python 설치 및 PATH를 확인하세요.`,
    });
    engine = null;
    rl = null;
  });

  engine.stderr.on('data', (d) => {
    sendEvent({ type: 'engine_stderr', message: d.toString() });
  });

  engine.on('exit', (code) => {
    sendEvent({ type: 'engine_exit', code });
    engine = null;
    rl = null;
  });

  rl = readline.createInterface({ input: engine.stdout });
  rl.on('line', (line) => {
    const s = line.trim();
    if (!s) return;
    try {
      sendEvent(JSON.parse(s));
    } catch (e) {
      sendEvent({ type: 'engine_stderr', message: s });
    }
  });
}

function sendToEngine(obj) {
  if (!engine) startEngine();
  if (engine && engine.stdin && engine.stdin.writable) {
    engine.stdin.write(JSON.stringify(obj) + '\n');
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1720,
    height: 940,
    minWidth: 1180,
    minHeight: 640,
    backgroundColor: '#0f1117',
    title: '자막 생성기',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
}

async function runSetup() {
  try {
    runtimeInfo = await bootstrap.ensureRuntime((p) =>
      sendEvent({ type: 'setup:progress', ...p }));
    sendEvent({ type: 'setup:done' });
    startEngine();
    if (app.isPackaged) setTimeout(() => updater.check(), 1500);
  } catch (e) {
    sendEvent({ type: 'setup:error', message: (e && e.message) || String(e) });
  }
}

app.whenReady().then(() => {
  createWindow();
  updater.initUpdater(sendEvent);
  // 새로고침(Ctrl+R) 시에도 setup:done 을 다시 보내 오버레이가 멈추지 않게 on 사용.
  // 이미 설치 완료면 ensureRuntime이 즉시 반환하므로 가볍게 끝남.
  win.webContents.on('did-finish-load', () => { runSetup(); });
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

ipcMain.on('setup:retry', () => runSetup());
ipcMain.on('update:check', () => updater.check());
ipcMain.on('update:download', () => updater.download());
ipcMain.on('update:install', () => updater.install());

app.on('window-all-closed', () => {
  if (engine) {
    try { sendToEngine({ cmd: 'shutdown' }); } catch (e) { /* noop */ }
  }
  if (process.platform !== 'darwin') app.quit();
});

// ---------- IPC ----------
ipcMain.handle('dialog:openFolder', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
  if (r.canceled || !r.filePaths.length) return null;
  return r.filePaths[0];
});

ipcMain.handle('fs:hasSubtitle', (e, videoPath, fmt) => {
  try {
    const base = videoPath.replace(/\.[^/.]+$/, '');
    return fs.existsSync(`${base}.${fmt || 'srt'}`);
  } catch (err) {
    return false;
  }
});

// 영상에 딸린 기존 자막(.srt 우선, 없으면 .smi) 찾기 → {path, fmt} | null
ipcMain.handle('fs:findSubtitle', (e, videoPath) => {
  try {
    const base = videoPath.replace(/\.[^/.]+$/, '');
    for (const fmt of ['srt', 'smi']) {
      const p = `${base}.${fmt}`;
      if (fs.existsSync(p)) return { path: p, fmt };
    }
  } catch (err) { /* noop */ }
  return null;
});

ipcMain.on('engine:cmd', (e, cmd) => sendToEngine(cmd));

// 영상 썸네일 생성 (ffmpeg로 한 프레임 추출 → JPEG → data URL 반환). 캐시 사용.
ipcMain.handle('thumb:get', async (e, videoPath) => {
  return await new Promise((resolve) => {
    const asDataUrl = (fp) => {
      try { resolve('data:image/jpeg;base64,' + fs.readFileSync(fp).toString('base64')); }
      catch (err) { resolve(null); }
    };
    try {
      fs.mkdirSync(THUMB_DIR, { recursive: true });
      const key = crypto.createHash('md5').update(videoPath).digest('hex');
      const out = path.join(THUMB_DIR, key + '.jpg');
      if (fs.existsSync(out)) { asDataUrl(out); return; }
      const ff = resolveFfmpeg();
      const p = spawn(ff, ['-nostdin', '-y', '-ss', '3', '-i', videoPath,
        '-frames:v', '1', '-vf', 'scale=160:-1', '-q:v', '5', out],
        { stdio: 'ignore' });
      let done = false;
      const finish = () => {
        if (done) return; done = true;
        if (fs.existsSync(out)) asDataUrl(out); else resolve(null);
      };
      p.on('error', () => { if (!done) { done = true; resolve(null); } });
      p.on('exit', finish);
      setTimeout(() => { try { p.kill(); } catch (e2) { /* noop */ } if (!done) { done = true; resolve(null); } }, 15000);
    } catch (err) { resolve(null); }
  });
});

ipcMain.on('shell:showItem', (e, p) => {
  try { shell.showItemInFolder(p); } catch (err) { /* noop */ }
});

ipcMain.on('shell:openExternal', (e, url) => {
  try {
    if (typeof url === 'string' && /^https:\/\//i.test(url)) shell.openExternal(url);
  } catch (err) { /* noop */ }
});
