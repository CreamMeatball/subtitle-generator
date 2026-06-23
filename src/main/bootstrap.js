'use strict';
/**
 * 런타임 부트스트랩.
 *
 * 설치 후 첫 실행 시, 사용자 시스템과 격리된 가상환경(%APPDATA%/.../runtime/venv)을
 * 만들고 Python 의존성을 자동 설치한다. CUDA 등 무거운 GPU 런타임은 설치 파일에
 * 내장하지 않고, NVIDIA가 PyPI에 공식 배포하는 휠을 (GPU가 있을 때만) 내려받아
 * 그 격리 환경 안에만 설치한다.
 *
 * - 개발 모드(app.isPackaged=false): 기존처럼 시스템/venv python 사용(설치 생략).
 * - 패키지 모드: resources/python(동봉 standalone python)으로 venv 생성 후 설치.
 */
const { app } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');

const SETUP_VERSION = 'v1';

function isPackaged() { return app.isPackaged; }

function bundledPython() {
  // 패키지: 동봉 standalone python. 개발: SUBGEN_PYTHON 또는 PATH의 python.
  if (isPackaged()) return path.join(process.resourcesPath, 'python', 'python.exe');
  return process.env.SUBGEN_PYTHON || 'python';
}

function engineDir() {
  if (isPackaged()) return path.join(process.resourcesPath, 'engine');
  return path.join(__dirname, '..', '..', 'python');
}

function ffmpegPath() {
  const p = isPackaged()
    ? path.join(process.resourcesPath, 'ffmpeg', 'ffmpeg.exe')
    : (process.env.FFMPEG_PATH || '');
  return (p && fs.existsSync(p)) ? p : '';
}

function runtimeDir() { return path.join(app.getPath('userData'), 'runtime'); }
function venvDir() { return path.join(runtimeDir(), 'venv'); }
function venvPython() {
  return process.platform === 'win32'
    ? path.join(venvDir(), 'Scripts', 'python.exe')
    : path.join(venvDir(), 'bin', 'python');
}
function markerFile() { return path.join(runtimeDir(), `ready-${SETUP_VERSION}.json`); }

function run(cmd, args, onLine) {
  return new Promise((resolve, reject) => {
    let p;
    try { p = spawn(cmd, args, { windowsHide: true }); }
    catch (e) { reject(e); return; }
    let tail = '';
    const sink = (d) => {
      const s = d.toString();
      tail = (tail + s).slice(-1200);
      if (onLine) onLine(s);
    };
    if (p.stdout) p.stdout.on('data', sink);
    if (p.stderr) p.stderr.on('data', sink);
    p.on('error', reject);
    p.on('exit', (code) => code === 0
      ? resolve()
      : reject(new Error(`종료코드 ${code}\n${tail.slice(-600)}`)));
  });
}

function hasNvidiaGpu() {
  try { execSync('nvidia-smi -L', { stdio: 'ignore' }); return true; }
  catch (e) { return false; }
}

/**
 * 런타임을 보장하고 {python, engineDir, ffmpeg} 반환.
 * onProgress({step,message,detail}) 로 진행 상황 통지.
 */
async function ensureRuntime(onProgress) {
  const report = (step, message, detail, percent) =>
    onProgress && onProgress({ step, message, detail, percent });

  // 개발 모드: 사용자가 직접 구성한 환경 사용
  if (!isPackaged()) {
    return { python: bundledPython(), engineDir: engineDir(), ffmpeg: ffmpegPath() };
  }

  fs.mkdirSync(runtimeDir(), { recursive: true });

  // 이미 설치 완료
  if (fs.existsSync(markerFile()) && fs.existsSync(venvPython())) {
    return { python: venvPython(), engineDir: engineDir(), ffmpeg: ffmpegPath() };
  }

  const py = bundledPython();
  report('venv', '독립 Python 환경을 만드는 중…', null, 6);
  await run(py, ['-m', 'venv', venvDir()]);

  const vpy = venvPython();
  report('pip', 'pip 준비 중…', null, 12);
  await run(vpy, ['-m', 'pip', 'install', '--upgrade', 'pip', 'wheel']);

  report('deps', '필수 라이브러리 설치 중… (최초 1회, 수 분 소요)', null, 16);
  const reqs = path.join(engineDir(), 'requirements-app.txt');
  let collected = 0;
  await run(vpy, ['-m', 'pip', 'install', '-r', reqs], (line) => {
    const m = /^(Collecting|Downloading)\s+([^\s]+)/m.exec(line);
    if (m) {
      collected += 1;
      const pct = Math.min(88, 16 + collected * 2);
      report('deps', '필수 라이브러리 설치 중…', `${m[1]} ${m[2]}`.slice(0, 60), pct);
    }
  });
  report('deps', '설치 마무리 중…', null, 90);

  // GPU 가속: 설치 파일에 내장하지 않고 NVIDIA 공식 휠을 격리 환경에만 설치
  if (hasNvidiaGpu()) {
    report('gpu', 'GPU 가속 런타임 설치 중… (NVIDIA 공식 패키지)', null, 93);
    try {
      // cuDNN은 9.x로 고정한다. 현재 faster-whisper(ctranslate2 4.x)는 cuDNN 9를
      // 사용하므로, pip가 향후 비호환 버전(예: 10)을 받아 'DLL 초기화 실패
      // (WinError 1114)'가 나는 것을 방지한다. DLL 검색 경로는 엔진(transcribe.py)이
      // 런타임에 추가하므로 CUDA Toolkit 별도 설치는 불필요.
      await run(vpy, ['-m', 'pip', 'install',
        'nvidia-cublas-cu12', 'nvidia-cudnn-cu12>=9.1,<10']);
    } catch (e) {
      // GPU 런타임 실패해도 CPU로 자동 동작하므로 무시
      report('gpu', 'GPU 런타임 설치 건너뜀 (CPU로 동작)', null, 97);
    }
  }
  report('finish', '마무리 중…', null, 98);

  fs.writeFileSync(markerFile(),
    JSON.stringify({ version: SETUP_VERSION, at: Date.now(), gpu: hasNvidiaGpu() }));
  return { python: venvPython(), engineDir: engineDir(), ffmpeg: ffmpegPath() };
}

/**
 * 설치된 런타임(venv + 완료 표식)을 삭제한다. 다음 ensureRuntime 호출 시 새로 설치됨.
 * Windows에서 venv의 python.exe가 사용 중이면 삭제가 실패하므로, 호출 전에
 * 엔진 프로세스를 반드시 종료해야 한다. 일시적 잠금은 잠깐 대기 후 재시도한다.
 */
async function removeRuntime() {
  if (!isPackaged()) return;  // 개발 모드에는 별도 런타임이 없음
  const dir = runtimeDir();
  for (let i = 0; i < 5; i++) {
    try {
      if (fs.existsSync(dir)) fs.rmSync(dir, { recursive: true, force: true });
      return;
    } catch (e) {
      // 파일 잠금(EBUSY/EPERM) — 잠깐 기다렸다 재시도
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  // 마지막 시도: 전체 삭제가 안 되면 표식만이라도 지워 재설치를 강제
  try { if (fs.existsSync(markerFile())) fs.rmSync(markerFile(), { force: true }); }
  catch (e) { /* noop */ }
}

module.exports = {
  ensureRuntime, removeRuntime, engineDir, ffmpegPath, venvPython, runtimeDir, markerFile,
};
