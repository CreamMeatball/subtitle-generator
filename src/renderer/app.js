'use strict';
/* 렌더러 로직: 폴더 스캔, 파일 선택(드래그/Shift/Ctrl), 큐 시각화, 설정. */

// [value, 표시라벨]. 값에 '/'가 있으면 커스텀 HuggingFace 모델(최초 1회 CT2 변환).
const MODELS = [
  ['tiny', 'tiny (가장 빠름)'],
  ['base', 'base'],
  ['small', 'small'],
  ['medium', 'medium'],
  ['large-v3', 'large-v3 (정확/느림)'],
  ['large-v3-turbo', 'large-v3-turbo (빠르고 정확)'],
];
const MODEL_LABEL = Object.fromEntries(MODELS.map(([v, l]) => [v, l]));
const VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.ts',
  '.m4v', '.mpg', '.mpeg', '.m2ts', '.mts', '.vob', '.ogv', '.3gp',
  '.mp3', '.wav', '.m4a', '.aac', '.flac', '.opus'];
function isVideoFile(name) {
  const i = (name || '').lastIndexOf('.');
  return i >= 0 && VIDEO_EXTS.includes(name.slice(i).toLowerCase());
}
// 익명 사용 통계(설치/실행 수) 카운터 엔드포인트.
// Cloudflare Worker 배포 후 그 URL을 여기에 넣으세요. 비워두면 아무것도 전송 안 함.
// 예: 'https://subgen-counter.<your-subdomain>.workers.dev'
const ANALYTICS_URL = 'https://subgen-counter.pch5445.workers.dev';

// '건의하기' 전송용 Web3Forms access key.
// https://web3forms.com 에서 수신 이메일(subtitlegeneratorai@gmail.com)로 키를 발급받아 여기에 넣으세요.
// 실제 수신 메일 주소는 이 키 뒤에 숨겨져 사용자에게 노출되지 않습니다.
// 비워두면 건의 전송이 비활성화됩니다.
const FEEDBACK_ACCESS_KEY = '6bc5b494-7723-4311-95ea-56285a173116';

const LANGS = [
  ['auto', '자동 감지'], ['ko', '한국어'], ['en', '영어'], ['ja', '일본어'],
  ['zh', '중국어'], ['es', '스페인어'], ['fr', '프랑스어'], ['de', '독일어'],
  ['ru', '러시아어'], ['vi', '베트남어'], ['th', '태국어'],
];
// 기본 튜닝 프로필(전사 정확도용 initial_prompt). 원본(말하는) 언어로 작성.
const DEFAULT_TUNING = [
  { id: 'general', name: '일반', text: '' },
  { id: 'lecture', name: '강의/세미나', text: '전문 강의·세미나 녹화. 개념, 정의, 예시, 증명, 정리, 공식, 가설, 결론, 요약, 과제, 시험, 참고문헌, 질의응답, 수강생.' },
  { id: 'meeting', name: '회의/업무', text: '업무 회의 녹음. 안건, 일정, 액션 아이템, 담당자, 마감일, 예산, KPI, 우선순위, 리스크, 의사결정, 공유, 피드백, 회의록, 분기.' },
  { id: 'interview', name: '인터뷰/팟캐스트', text: '대담·인터뷰·팟캐스트. 진행자와 게스트가 번갈아 대화하는 구어체. 질문, 답변, 에피소드, 사연, 코너, 청취자.' },
  { id: 'drama', name: '드라마/영화', text: '드라마·영화 대사. 자연스러운 구어체와 감정 표현, 반말과 존댓말, 인물 간 대화, 독백, 나레이션, 회상.' },
  { id: 'news', name: '뉴스/시사', text: '뉴스 보도. 앵커, 기자, 특파원, 인터뷰. 정치, 경제, 사회, 국제, 증시, 환율, 부동산, 정부, 국회, 발표, 브리핑, 속보.' },
  { id: 'vlog', name: '브이로그/일상', text: '일상 브이로그. 구어체 혼잣말과 설명. 카페, 맛집, 여행, 운동, 쇼핑, 요리, 리뷰, 추천, 브이로그, 일상.' },
  { id: 'it', name: 'IT/개발', text: 'IT·개발 발표·강의. API, 서버, 클라이언트, 데이터베이스, 배포, 빌드, 컨테이너, 쿠버네티스, 도커, 깃, 리팩터링, 버그, 디버깅, 프레임워크, 라이브러리, 클라우드, 머신러닝, 모델.' },
  { id: 'esports', name: 'e스포츠(종합)', text: '프로 게임 대회 중계. 세트, 매치, 경기, 라운드, 결승, 4강, 플레이오프, 시드, 우승, MVP, 빌드, 전략, 교전, 클러치.' },
];

// 기본 번역 프로필(용어집). '원문 => 번역', 오른쪽 비우면 원문 유지.
const DEFAULT_TRANS = [
  { id: 'tp_lol', name: 'LoL 챔피언·인명(한글표기)', text: 'Faker => 페이커\nZeus => 제우스\nOner => 오너\nGumayusi => 구마유시\nKeria => 케리아\nChovy => 쵸비\nAzir => 아지르\nAhri => 아리\nYasuo => 야스오\nThresh => 쓰레쉬\nWorlds =>\nLCK =>' },
  { id: 'tp_lck_team', name: 'LCK 팀/대회(원문 유지)', text: 'T1 =>\nGen.G =>\nKT Rolster =>\nHanwha Life =>\nDRX =>\nDplus KIA =>\nNongshim =>\nLCK =>\nMSI =>\nWorlds =>' },
  { id: 'tp_it', name: 'IT 용어(원문 유지)', text: 'API =>\nGPU =>\nCPU =>\nSDK =>\nUI =>\nUX =>\nDocker =>\nKubernetes =>\nGit =>\nPython =>\nJavaScript =>\nLLM =>' },
  { id: 'tp_names', name: '인명 표기(예시)', text: 'John => 존\nMike => 마이크\nSarah => 세라\nNew York => 뉴욕' },
];

const DEFAULTS = {
  model: 'large-v3-turbo', language: 'auto', target: 'ko', profileId: 'general',
  fmt: 'srt', concurrency: 1, maxDur: 7, wordTs: false,
  reduceHallu: false, overwrite: 'overwrite', subBackup: 'backup',
  theme: 'night', apiNoticeShown: false, tutorialDone: false, updateMode: 'auto',
  analytics: true,
  backend: 'none', deeplKey: '', googleKey: '', kakaoKey: '', prompt: '',
  tuningProfiles: DEFAULT_TUNING.map((p) => ({ ...p })),
  transProfiles: DEFAULT_TRANS.map((p) => ({ ...p })),
  transProfileId: '',
};

const $ = (id) => document.getElementById(id);

let settings = loadSettings();
let profEditId = null;           // 설정 모달에서 편집 중인 튜닝 프로필 id
let transEditId = null;          // 설정 모달에서 편집 중인 번역 프로필 id

function parseGlossary(text) {
  const out = [];
  for (const line of (text || '').split('\n')) {
    const s = line.trim();
    if (!s) continue;
    const idx = s.indexOf('=>');
    if (idx < 0) { out.push({ src: s, keep: true }); continue; }
    const src = s.slice(0, idx).trim();
    const dst = s.slice(idx + 2).trim();
    if (!src) continue;
    if (dst) out.push({ src, dst });
    else out.push({ src, keep: true });
  }
  return out;
}
let files = [];                 // 스캔된 파일 [{path,name,size,duration?}]
let selected = new Set();       // 선택된 인덱스(전체 files 기준)
let dragging = false;
let anchor = -1;
let fileFilter = '';            // 제목 검색어
let subFound = {};             // 파일 인덱스 → 기존 자막 존재 여부
let started = false;            // engine start 한 번만
const jobs = new Map();         // id -> job dict
const jobEls = new Map();       // id -> DOM element

/* ---------- 설정 ---------- */
function loadSettings() {
  let s;
  try {
    const raw = localStorage.getItem('subgen.settings');
    s = raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch (e) { s = { ...DEFAULTS }; }
  // 기존 사용자에게도 새 기본 프로필을 보강(없는 id만 추가, 사용자 항목은 유지)
  s.tuningProfiles = mergeDefaults(s.tuningProfiles, DEFAULT_TUNING);
  s.transProfiles = mergeDefaults(s.transProfiles, DEFAULT_TRANS);
  return s;
}
function mergeDefaults(userList, defaults) {
  const out = Array.isArray(userList) ? userList.slice() : [];
  const have = new Set(out.map((p) => p && p.id));
  for (const d of defaults) if (!have.has(d.id)) out.push({ ...d });
  return out;
}
function saveSettings() {
  try { localStorage.setItem('subgen.settings', JSON.stringify(settings)); } catch (e) { /* noop */ }
}

/* ---------- 유틸 ---------- */
function fmtSize(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)}${u[i]}`;
}
function fmtDur(s) {
  if (!s) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); const ss = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
    : `${m}:${String(ss).padStart(2, '0')}`;
}
let activityTimer = null;
function showActivity(text) {
  $('activityText').textContent = text;
  $('activity').hidden = false;
  // 일정 시간 새 준비 메시지가 없으면 자동으로 숨김(중단/누락 대비 안전장치)
  if (activityTimer) clearTimeout(activityTimer);
  // 실제 추출/분석은 큰 파일에서 수십초~분이 걸릴 수 있어 안전 타임아웃을 넉넉히 둠.
  // 평소엔 progress 시작이나 작업 종료 시 숨겨진다.
  activityTimer = setTimeout(hideActivity, 180000);
}
function hideActivity() {
  $('activity').hidden = true;
  if (activityTimer) { clearTimeout(activityTimer); activityTimer = null; }
}
function anyRunning() {
  for (const j of jobs.values()) if (j.status === 'running') return true;
  return false;
}

/* ---------- 업데이트 배너 ---------- */
let manualCheck = false;
let updateAct = null;
function showUpdateBar(msg, actionLabel, act) {
  $('updateMsg').textContent = msg;
  updateAct = act || null;
  const btn = $('updateAction');
  if (actionLabel) { btn.textContent = actionLabel; btn.hidden = false; }
  else btn.hidden = true;
  $('updateBar').hidden = false;
}

/* ---------- 썸네일 로더 (순차 처리 + 캐시) ---------- */
const thumbCache = new Map();      // path -> dataURL|null
const pendingThumbs = new Set();
const thumbQueue = [];
let thumbBusy = false;

function enqueueThumb(p) {
  if (thumbCache.has(p) || pendingThumbs.has(p)) return;
  pendingThumbs.add(p);
  thumbQueue.push(p);
  pumpThumbs();
}
async function pumpThumbs() {
  if (thumbBusy) return;
  thumbBusy = true;
  while (thumbQueue.length) {
    const p = thumbQueue.shift();
    let d = null;
    try { d = await window.api.thumb(p); } catch (e) { d = null; }
    thumbCache.set(p, d);
    pendingThumbs.delete(p);
    applyThumbForPath(p);
  }
  thumbBusy = false;
}
function applyThumbForPath(p) {
  const d = thumbCache.get(p);
  if (!d) return;
  for (const img of document.querySelectorAll('img.thumb[data-fi]')) {
    const f = files[Number(img.dataset.fi)];
    if (f && f.path === p) img.src = d;
  }
  for (const img of document.querySelectorAll('img.thumb[data-jid]')) {
    const j = jobs.get(Number(img.dataset.jid));
    if (j && j.path === p) img.src = d;
  }
}
function loadThumbFor(img, p) {
  if (!img || !p) return;
  const d = thumbCache.get(p);
  if (d) { img.src = d; } else { enqueueThumb(p); }
}
function applyFileThumbs() {
  for (const img of document.querySelectorAll('img.thumb[data-fi]')) {
    const f = files[Number(img.dataset.fi)];
    if (f) loadThumbFor(img, f.path);
  }
}

function toast(msg, kind) {
  const el = document.createElement('div');
  el.className = `toast ${kind || ''}`;
  el.textContent = msg;
  $('toastWrap').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

/* ---------- 셀렉트 초기화 ---------- */
function populateSelects() {
  for (const sel of [$('modelSel'), $('setModel')]) {
    sel.innerHTML = MODELS
      .map(([v, l]) => `<option value="${v}">${escapeHtml(l)}</option>`).join('');
  }
  for (const sel of [$('langSel'), $('setLang')]) {
    sel.innerHTML = LANGS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  }
  // 번역 on/off는 '번역 모델'(백엔드)에서 정하므로 대상 언어는 언어 목록만
  const targetOpts = LANGS.filter(([v]) => v !== 'auto')
    .map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  $('targetSel').innerHTML = targetOpts;
  $('setTarget').innerHTML = targetOpts;
  populateProfiles();
  populateTransProfiles();
  applySettingsToUI();
}
function populateProfiles() {
  const list = settings.tuningProfiles || [];
  const opts = list
    .map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
  $('profileSel').innerHTML = opts;
  $('setProfile').innerHTML = list.length ? opts : '<option value="">(없음 — 새로 만들기)</option>';
}
function loadProfEditor(id) {
  const list = settings.tuningProfiles || [];
  const p = list.find((x) => x.id === id) || list[0] || null;
  profEditId = p ? p.id : null;
  $('setProfName').value = p ? p.name : '';
  $('setProfText').value = p ? p.text : '';
  if (p) $('setProfile').value = p.id;
}
function commitProfEditor() {
  if (!profEditId) return;
  const p = (settings.tuningProfiles || []).find((x) => x.id === profEditId);
  if (p) {
    p.name = $('setProfName').value.trim() || p.name;
    p.text = $('setProfText').value;
  }
}
function populateTransProfiles() {
  const list = settings.transProfiles || [];
  $('transProfileSel').innerHTML = '<option value="">(없음)</option>' +
    list.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
  $('setTransProfile').innerHTML = list.length
    ? list.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('')
    : '<option value="">(없음 — 새로 만들기)</option>';
}
function loadTransEditor(id) {
  const list = settings.transProfiles || [];
  const p = list.find((x) => x.id === id) || list[0] || null;
  transEditId = p ? p.id : null;
  $('setTransName').value = p ? p.name : '';
  $('setTransText').value = p ? p.text : '';
  if (p) $('setTransProfile').value = p.id;
}
function commitTransEditor() {
  if (!transEditId) return;
  const p = (settings.transProfiles || []).find((x) => x.id === transEditId);
  if (p) {
    p.name = $('setTransName').value.trim() || p.name;
    p.text = $('setTransText').value;
  }
}
function applySettingsToUI() {
  $('modelSel').value = settings.model;
  $('backendSel').value = settings.backend;
  $('langSel').value = settings.language;
  $('targetSel').value = settings.target;
  $('profileSel').value = settings.profileId;
  $('transProfileSel').value = settings.transProfileId || '';
  $('fmtSel').value = settings.fmt;
  $('concInput').value = settings.concurrency;
  $('setModel').value = settings.model;
  $('setLang').value = settings.language;
  $('setTarget').value = settings.target;
  $('setBackend').value = settings.backend;
  $('setDeeplKey').value = settings.deeplKey || '';
  $('setGoogleKey').value = settings.googleKey || '';
  $('setKakaoKey').value = settings.kakaoKey || '';
  $('setFmt').value = settings.fmt;
  $('setConc').value = settings.concurrency;
  $('setMaxDur').value = settings.maxDur;
  $('setWordTs').checked = settings.wordTs !== false;
  $('setReduceHallu').checked = settings.reduceHallu === true;
  $('setOverwrite').value = settings.overwrite || 'overwrite';
  $('setSubBackup').value = settings.subBackup || 'backup';
  $('setAutoUpdate').value = settings.updateMode || 'auto';
  $('setAnalytics').checked = settings.analytics !== false;
  $('setPrompt').value = settings.prompt || '';
  loadProfEditor(profEditId || settings.profileId ||
    ((settings.tuningProfiles && settings.tuningProfiles[0]) || {}).id);
  loadTransEditor(transEditId || settings.transProfileId ||
    ((settings.transProfiles && settings.transProfiles[0]) || {}).id);
}

/* ---------- 파일 리스트 ---------- */
async function openFolder() {
  const dir = await window.api.openFolder();
  if (!dir) return;
  $('folderPath').textContent = dir;
  window.api.send({ cmd: 'scan', dir, with_duration: true });
}

function visibleFileIndices() {
  const q = fileFilter.trim().toLowerCase();
  const out = [];
  files.forEach((f, i) => {
    if (!q || (f.name || '').toLowerCase().includes(q)) out.push(i);
  });
  return out;
}

function onDropFiles(e) {
  e.preventDefault();
  document.body.classList.remove('dragover');
  const added = [];
  for (const f of (e.dataTransfer ? e.dataTransfer.files : [])) {
    if (!isVideoFile(f.name)) continue;
    const p = window.api.pathForFile(f);
    if (!p || files.some((x) => x.path === p)) continue;
    files.push({ path: p, name: f.name, size: f.size });
    added.push(f.name);
  }
  if (added.length) {
    renderFiles();
    toast(`${added.length}개 파일을 추가했습니다.`, 'ok');
  } else {
    toast('추가할 영상 파일이 없습니다.', 'error');
  }
}

function renderFiles() {
  const list = $('fileList');
  const empty = $('filesEmpty');
  const vis = visibleFileIndices();
  if (!files.length || !vis.length) {
    list.innerHTML = '';
    empty.style.display = 'block';
    empty.querySelector('p').textContent = files.length
      ? `검색 결과가 없습니다: "${fileFilter}"`
      : '여기에 영상 목록이 표시됩니다.';
    updateSelCount();
    return;
  }
  empty.style.display = 'none';
  list.innerHTML = vis.map((i) => {
    const f = files[i];
    return `
    <li class="file-row ${selected.has(i) ? 'selected' : ''}" data-i="${i}">
      <img class="thumb" data-fi="${i}" alt="" draggable="false" />
      <span class="fname">${escapeHtml(f.name)}</span>
      <span class="sub-dot" data-sub="${i}"></span>
      <span class="fmeta">${f.duration ? fmtDur(f.duration) + ' · ' : ''}${fmtSize(f.size)}</span>
    </li>`;
  }).join('');
  updateSelCount();
  refreshSubtitleDots();
  applyFileThumbs();
}

async function refreshSubtitleDots() {
  for (let i = 0; i < files.length; i++) {
    try {
      const found = await window.api.findSubtitle(files[i].path);
      subFound[i] = !!found;
      const dot = document.querySelector(`[data-sub="${i}"]`);
      if (dot) dot.textContent = found ? `● ${found.fmt} 있음` : '';
    } catch (e) { subFound[i] = false; }
  }
  updateSelCount();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function setSelection(next) {
  selected = next;
  for (const row of document.querySelectorAll('.file-row')) {
    const i = Number(row.dataset.i);
    row.classList.toggle('selected', selected.has(i));
  }
  updateSelCount();
}
function rangeSetVisible(a, b) {
  const vis = visibleFileIndices();
  const ia = vis.indexOf(a);
  const ib = vis.indexOf(b);
  if (ia < 0 || ib < 0) return new Set([b]);
  const [lo, hi] = ia < ib ? [ia, ib] : [ib, ia];
  return new Set(vis.slice(lo, hi + 1));
}
function updateSelCount() {
  const vis = visibleFileIndices();
  $('selCount').textContent = `선택 ${selected.size}`;
  $('selectAll').checked = vis.length > 0 && vis.every((i) => selected.has(i));
  $('generateBtn').disabled = selected.size === 0;
  const selWithSub = [...selected].filter((i) => subFound[i]).length;
  $('translateBtn').disabled = selWithSub === 0;
}

/* 드래그/클릭 선택 */
function onRowMouseDown(e) {
  const row = e.target.closest('.file-row');
  if (!row) return;
  const i = Number(row.dataset.i);
  if (e.shiftKey && anchor >= 0) {
    setSelection(rangeSetVisible(anchor, i));
  } else if (e.ctrlKey || e.metaKey) {
    const next = new Set(selected);
    if (next.has(i)) next.delete(i); else next.add(i);
    setSelection(next);
    anchor = i;
  } else {
    setSelection(new Set([i]));
    anchor = i;
    dragging = true;
  }
}
function onRowMouseEnter(e) {
  if (!dragging) return;
  const row = e.target.closest('.file-row');
  if (!row) return;
  const i = Number(row.dataset.i);
  setSelection(rangeSetVisible(anchor, i));
}

/* ---------- 자막 생성 ---------- */
function generate() {
  if (selected.size === 0) return;
  syncSettingsFromBar();
  const paths = [...selected].sort((a, b) => a - b).map((i) => files[i].path);
  const tp = (settings.transProfiles || []).find((p) => p.id === settings.transProfileId);
  const tune = (settings.tuningProfiles || []).find((p) => p.id === settings.profileId);
  const promptText = [tune ? tune.text : '', settings.prompt || '']
    .map((s) => (s || '').trim()).filter(Boolean).join(' ');
  const options = {
    model: settings.model,
    language: settings.language,
    fmt: settings.fmt,
    max_subtitle_dur: Number(settings.maxDur) || 0,
    word_timestamps: settings.wordTs !== false,
    condition_on_previous_text: settings.reduceHallu !== true,
    hallucination_silence_threshold: settings.reduceHallu === true ? 2.0 : null,
    overwrite_policy: settings.overwrite || 'overwrite',
    profile_name: tune ? tune.name : '',
    custom_prompt: settings.prompt || '',
    initial_prompt: promptText || null,
    translate: settings.backend !== 'none' && !!settings.target,
    target_lang: settings.target || null,
    translate_backend: settings.backend,
    api_key: apiKeyFor(settings.backend),
    glossary: tp ? parseGlossary(tp.text) : [],
    tprofile_name: tp ? tp.name : '',
  };
  window.api.send({ cmd: 'set_concurrency', value: Number(settings.concurrency) });
  window.api.send({ cmd: 'add', paths, options });
  if (!started) { window.api.send({ cmd: 'start' }); started = true; }
  showActivity('작업 준비 중… (모델 로드/다운로드가 필요할 수 있습니다)');
  toast(`${paths.length}개 작업을 큐에 추가했습니다.`, 'ok');
}

function translateExisting() {
  const idxs = [...selected].filter((i) => subFound[i]).sort((a, b) => a - b);
  if (!idxs.length) return;
  syncSettingsFromBar();
  if (settings.backend === 'none') {
    toast('먼저 번역 모델(Google·카카오·DeepL·NLLB)을 선택하세요.', 'error');
    return;
  }
  if (!settings.target) {
    toast('먼저 번역 대상 언어를 선택하세요.', 'error');
    return;
  }
  const paths = idxs.map((i) => files[i].path);
  const tp = (settings.transProfiles || []).find((p) => p.id === settings.transProfileId);
  const options = {
    mode: 'translate_only',
    language: settings.language,
    translate: true,
    target_lang: settings.target,
    translate_backend: settings.backend,
    api_key: apiKeyFor(settings.backend),
    glossary: tp ? parseGlossary(tp.text) : [],
    tprofile_name: tp ? tp.name : '',
    subtitle_backup: settings.subBackup || 'backup',
    max_subtitle_dur: 0,
    profile_name: '(번역 전용)',
  };
  window.api.send({ cmd: 'set_concurrency', value: Number(settings.concurrency) });
  window.api.send({ cmd: 'add', paths, options });
  if (!started) { window.api.send({ cmd: 'start' }); started = true; }
  showActivity('기존 자막 번역 준비 중…');
  toast(`${paths.length}개 자막 번역을 큐에 추가했습니다.`, 'ok');
}

function applyTheme() {
  document.body.classList.toggle('day', settings.theme === 'day');
  $('themeBtn').textContent = settings.theme === 'day' ? '☀️' : '🌙';
}

// 익명 실행 통계 핑(개인정보 없음). install=최초 1회, launch=실행마다. 설정에서 끌 수 있음.
function pingAnalytics() {
  if (!ANALYTICS_URL || settings.analytics === false) return;
  const send = (event) => {
    try {
      fetch(`${ANALYTICS_URL}?event=${event}`, { method: 'POST', mode: 'no-cors', keepalive: true })
        .catch(() => {});
    } catch (e) { /* noop */ }
  };
  try {
    if (!localStorage.getItem('subgen.installed')) {
      localStorage.setItem('subgen.installed', '1');
      send('install');
    }
  } catch (e) { /* noop */ }
  send('launch');
}

/* ---------- 건의하기 ---------- */
function openFeedback() {
  $('feedbackText').value = '';
  $('feedbackEmail').value = '';
  $('feedbackModal').hidden = false;
  setTimeout(() => $('feedbackText').focus(), 50);
}
function closeFeedback() {
  $('feedbackModal').hidden = true;
}
async function submitFeedback() {
  const msg = $('feedbackText').value.trim();
  if (!msg) { toast('내용을 입력해주세요.', 'error'); $('feedbackText').focus(); return; }
  if (!FEEDBACK_ACCESS_KEY) { toast('건의 기능이 아직 설정되지 않았습니다.', 'error'); return; }
  const email = $('feedbackEmail').value.trim();
  const btn = $('feedbackSubmit');
  btn.disabled = true;
  const prevLabel = btn.textContent;
  btn.textContent = '전송 중…';
  try {
    const payload = {
      access_key: FEEDBACK_ACCESS_KEY,
      subject: '[자막 생성기] 건의 / 버그 제보',
      from_name: '자막 생성기 사용자',
      message: `${msg}\n\n---\n앱: ${navigator.userAgent}`,
    };
    if (email) payload.replyto = email;
    const res = await fetch('https://api.web3forms.com/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.success) {
      toast('건의가 전송되었습니다. 감사합니다!', 'ok');
      closeFeedback();
    } else {
      toast(`전송 실패: ${(data && data.message) || res.status}`, 'error');
    }
  } catch (e) {
    toast('전송 실패: 인터넷 연결을 확인해주세요.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = prevLabel;
  }
}

function toggleTheme() {
  settings.theme = settings.theme === 'day' ? 'night' : 'day';
  saveSettings();
  applyTheme();
}

/* ---------- 사용 가이드(튜토리얼) ---------- */
const TUT_PAGES = [
  {
    title: '사용 가이드 (1/2) — 기본 사용',
    html: `<ol class="tut-list">
      <li><b>📁 폴더 열기</b> 하거나, 창에 영상을 <b>끌어다 놓기</b>로 목록을 불러옵니다.</li>
      <li>목록에서 영상을 <b>선택</b>합니다 (드래그·Shift·Ctrl, 제목 검색 가능).</li>
      <li>하단에서 <b>모델·원본 언어·번역</b>을 고르고 <b>▶ 선택 항목 자막 생성</b>.</li>
      <li>오른쪽 <b>작업 큐</b>에서 진행률 확인 → 영상과 같은 폴더에 자막(.srt) 저장.</li>
    </ol>`,
  },
  {
    title: '사용 가이드 (2/2) — 알아두면 좋은 것',
    html: `<ul class="tut-list">
      <li><b>번역</b>: 하단 ‘번역 모델’에서 선택(기본 ‘번역 없음’). 품질은 <b>API(Google·카카오·DeepL)</b>를 권장합니다.</li>
      <li><b>▶ 기존 자막 번역</b>: 이미 자막이 있는 영상만 골라 <b>번역만</b> 수행(원본 자동 백업).</li>
      <li><b>프로필</b>: ‘튜닝 프로필’=전사 정확도(고유명사), ‘번역 프로필’=용어 표기 지정.</li>
      <li><b>설정(⚙)</b>: 자막 최대 표시 시간·환각 줄이기·자막 포맷·테마 등을 조절.</li>
    </ul>`,
  },
];
let tutPage = 0;
function maybeShowTutorial() {
  if (settings.tutorialDone) return;
  tutPage = 0;
  renderTut();
  $('tutorialOverlay').hidden = false;
}
function renderTut() {
  const p = TUT_PAGES[tutPage];
  $('tutTitle').textContent = p.title;
  $('tutBody').innerHTML = p.html;
  $('tutPage').textContent = tutPage + 1;
  $('tutPrev').hidden = tutPage === 0;
  $('tutNext').textContent = tutPage < TUT_PAGES.length - 1 ? '다음 →' : '시작하기';
}
function closeTut() { $('tutorialOverlay').hidden = true; }
function neverTut() { settings.tutorialDone = true; saveSettings(); closeTut(); }

function apiKeyFor(backend) {
  if (backend === 'google') return settings.googleKey || null;
  if (backend === 'kakao') return settings.kakaoKey || null;
  if (backend === 'online' || backend === 'deepl') return settings.deeplKey || null;
  return null;
}

// '번역 안함'에서 다른(특히 로컬) 모델로 처음 바꿀 때 API 권장 안내(최초 1회)
function maybeApiNotice() {
  if (settings.backend !== 'none' && !settings.apiNoticeShown) {
    settings.apiNoticeShown = true;
    saveSettings();
    toast('로컬 번역 모델은 성능이 부족할 수 있어 API 번역(Google·카카오·DeepL) 사용을 권장합니다.', 'error');
  }
}

function syncSettingsFromBar() {
  settings.model = $('modelSel').value;
  settings.backend = $('backendSel').value;
  settings.language = $('langSel').value;
  settings.target = $('targetSel').value;
  settings.profileId = $('profileSel').value;
  settings.transProfileId = $('transProfileSel').value;
  settings.fmt = $('fmtSel').value;
  settings.concurrency = Math.max(1, Number($('concInput').value) || 1);
  saveSettings();
}

/* ---------- 큐 렌더링 ---------- */
const ST_ICON = { queued: '…', running: '▶', done: '✓', failed: '✗', cancelled: '⊘', skipped: '⏭' };

function jobMetaText(job) {
  const pname = job.profile_name || '일반';
  const mlabel = MODEL_LABEL[job.model] || job.model || '';
  const parts = [`모델: ${mlabel}`, `프로필: ${pname}`];
  if (job.custom_prompt) parts.push(`추가:"${job.custom_prompt.slice(0, 16)}"`);
  if (job.translate && job.target_lang) {
    let t = `번역→${job.target_lang}`;
    if (job.tprofile_name) t += `[${job.tprofile_name}]`;
    parts.push(t);
  } else {
    parts.push('번역 없음');
  }
  return parts.join(' · ');
}

function ensureJobCard(job) {
  let el = jobEls.get(job.id);
  if (el) return el;
  $('queueEmpty').style.display = 'none';
  el = document.createElement('div');
  el.className = 'job';
  el.dataset.id = job.id;
  el.innerHTML = `
    <div class="job-top">
      <img class="thumb sm" data-jid="${job.id}" alt="" draggable="false" />
      <span class="job-status"></span>
      <span class="job-name"></span>
      <span class="muted job-pct"></span>
      <span class="job-actions"></span>
    </div>
    <div class="progress"><span></span></div>
    <div class="job-msg"></div>
    <div class="job-meta"></div>`;
  $('queueList').appendChild(el);
  jobEls.set(job.id, el);
  loadThumbFor(el.querySelector('img.thumb'), job.path);
  return el;
}

function updateJobCard(job) {
  const el = ensureJobCard(job);
  el.className = `job ${job.status}`;
  const statusEl = el.querySelector('.job-status');
  statusEl.className = `job-status st-${job.status}`;
  if (job.status === 'running') statusEl.innerHTML = '<span class="spinner"></span>';
  else statusEl.textContent = ST_ICON[job.status] || '?';
  el.querySelector('.job-name').textContent = job.name;
  const pct = `${Math.round((job.progress || 0) * 100)}%`;
  el.querySelector('.job-pct').textContent =
    job._elapsed ? `${pct} · ⏱${job._elapsed.toFixed(1)}초` : pct;
  el.querySelector('.progress > span').style.width = `${(job.progress || 0) * 100}%`;
  el.querySelector('.job-msg').textContent =
    job.error ? `오류: ${job.error}` : (job.message || '');
  el.querySelector('.job-meta').textContent = jobMetaText(job);
  const acts = el.querySelector('.job-actions');
  let html = '';
  if (job.status === 'running' || job.status === 'queued') {
    html = `<button class="btn" data-act="cancel" data-id="${job.id}">취소</button>`;
  } else if (job.status === 'failed' || job.status === 'cancelled') {
    html = `<button class="btn" data-act="retry" data-id="${job.id}">재시도</button>`;
  } else if (job.status === 'done' || job.status === 'skipped') {
    html = `<button class="btn" data-act="show" data-id="${job.id}">위치 열기</button>`;
  }
  acts.innerHTML = html;
}

function updateQueueSummary() {
  let q = 0; let r = 0; let d = 0; let f = 0; let s = 0;
  for (const j of jobs.values()) {
    if (j.status === 'queued') q++;
    else if (j.status === 'running') r++;
    else if (j.status === 'done') d++;
    else if (j.status === 'failed') f++;
    else if (j.status === 'skipped') s++;
  }
  $('queueSummary').textContent =
    `대기 ${q} · 진행 ${r} · 완료 ${d}${s ? ' · 건너뜀 ' + s : ''}${f ? ' · 실패 ' + f : ''}`;
  $('cancelAllBtn').disabled = (q + r) === 0;
}

function cancelAll() {
  let n = 0;
  for (const j of jobs.values()) {
    if (j.status === 'queued' || j.status === 'running') {
      window.api.send({ cmd: 'cancel', job_id: j.id });
      n++;
    }
  }
  if (n) toast(`${n}개 작업 취소를 요청했습니다.`);
}

function onQueueClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const id = Number(btn.dataset.id);
  const act = btn.dataset.act;
  const job = jobs.get(id);
  if (act === 'cancel') window.api.send({ cmd: 'cancel', job_id: id });
  else if (act === 'retry') window.api.send({ cmd: 'retry', job_id: id });
  else if (act === 'show' && job && job.output) window.api.showInFolder(job.output);
}

/* ---------- 엔진 이벤트 ---------- */
function handleEvent(ev) {
  switch (ev.type) {
    case 'ready':
      $('deviceBadge').textContent = '엔진 준비됨';
      break;
    case 'setup:progress':
      $('setupOverlay').style.display = 'flex';
      $('setupTitle').textContent = '초기 설정 중…';
      $('setupMsg').textContent = ev.message || '';
      $('setupDetail').textContent = ev.detail || '';
      if (typeof ev.percent === 'number') $('setupBar').style.width = ev.percent + '%';
      $('setupRetry').hidden = true;
      break;
    case 'setup:done':
      $('setupBar').style.width = '100%';
      setTimeout(() => { $('setupOverlay').style.display = 'none'; }, 250);
      maybeShowTutorial();
      break;
    case 'setup:error':
      $('setupOverlay').style.display = 'flex';
      $('setupTitle').textContent = '설정 중 오류가 발생했습니다';
      $('setupMsg').textContent = ev.message || '알 수 없는 오류';
      $('setupDetail').textContent = '인터넷 연결을 확인한 뒤 다시 시도하세요.';
      $('setupRetry').hidden = false;
      break;
    case 'scan_result':
      files = ev.items || [];
      selected = new Set();
      subFound = {};
      anchor = -1;
      fileFilter = '';
      $('fileSearch').value = '';
      renderFiles();
      toast(`${files.length}개 영상을 찾았습니다.`, 'ok');
      break;
    case 'job_added': {
      const j = ev.job;
      jobs.set(j.id, j);
      updateJobCard(j);
      updateQueueSummary();
      break;
    }
    case 'progress': {
      hideActivity(); // 전사 진행이 시작되면 상단 준비 바는 숨김
      const j = jobs.get(ev.job_id);
      if (j) { j.progress = ev.ratio; j.message = ev.message; updateJobCard(j); }
      break;
    }
    case 'job_state': {
      const j = jobs.get(ev.id) || ev;
      Object.assign(j, ev);
      jobs.set(j.id, j);
      const terminal = ['done', 'failed', 'cancelled', 'skipped'];
      if (ev.status === 'running' && !j._startAt) j._startAt = Date.now();
      if (terminal.includes(ev.status) && j._startAt && !j._elapsed) {
        j._elapsed = (Date.now() - j._startAt) / 1000;
      }
      updateJobCard(j);
      updateQueueSummary();
      if (ev.status === 'done') toast(`완료: ${ev.name}`, 'ok');
      else if (ev.status === 'failed') toast(`실패: ${ev.name} — ${ev.error || ''}`, 'error');
      else if (ev.status === 'skipped') toast(`건너뜀: ${ev.name}`);
      if (terminal.includes(ev.status) && !anyRunning()) hideActivity();
      break;
    }
    case 'log': {
      const m = ev.message || '';
      const di = m.indexOf('디바이스:');
      if (di >= 0) {
        $('deviceBadge').textContent = m.slice(di + '디바이스:'.length).trim();
      }
      showActivity(m); // 모든 준비/상태 로그를 상단 바에 표시(어디서 멈추는지 가시화)
      const j = jobs.get(ev.job_id);
      if (j && j.status === 'running') { j.message = m; updateJobCard(j); }
      break;
    }
    case 'engine_error':
      toast(ev.message, 'error');
      $('deviceBadge').textContent = '엔진 오류';
      hideActivity();
      break;
    case 'translate_error':
      toast(`번역 실패: ${ev.message}`, 'error');
      break;
    case 'vram_warning':
      toast(ev.message, 'error');
      if (ev.concurrency) {
        settings.concurrency = ev.concurrency;
        $('concInput').value = ev.concurrency;
      }
      break;
    case 'update:available':
      if ((settings.updateMode || 'auto') === 'manual') {
        showUpdateBar(`새 버전 v${ev.version} 이(가) 있습니다.`, '업데이트', 'download');
      } else {
        window.api.downloadUpdate();
        showUpdateBar('새 버전 다운로드 중…', null, null);
      }
      break;
    case 'update:progress':
      showUpdateBar(`업데이트 다운로드 중… ${ev.percent}%`, null, null);
      break;
    case 'update:downloaded':
      showUpdateBar(`업데이트 준비됨 (v${ev.version}) — 재시작하면 적용됩니다.`, '지금 재시작', 'install');
      break;
    case 'update:none':
      if (manualCheck) { toast('이미 최신 버전입니다.', 'ok'); manualCheck = false; }
      break;
    case 'update:error':
      if (manualCheck) { toast(`업데이트 확인 실패: ${ev.message}`, 'error'); manualCheck = false; }
      console.log('[update error]', ev.message);
      break;
    case 'engine_exit':
      $('deviceBadge').textContent = '엔진 종료됨';
      break;
    case 'engine_stderr':
      console.log('[engine stderr]', ev.message);
      break;
    default:
      break;
  }
}

/* ---------- 설정 모달 ---------- */
function openSettings() { applySettingsToUI(); $('settingsModal').hidden = false; }
function closeSettings() { $('settingsModal').hidden = true; }
function saveSettingsModal() {
  commitProfEditor();
  commitTransEditor();
  settings.model = $('setModel').value;
  settings.language = $('setLang').value;
  settings.target = $('setTarget').value;
  settings.backend = $('setBackend').value;
  settings.deeplKey = $('setDeeplKey').value;
  settings.googleKey = $('setGoogleKey').value;
  settings.kakaoKey = $('setKakaoKey').value;
  settings.fmt = $('setFmt').value;
  settings.concurrency = Math.max(1, Number($('setConc').value) || 1);
  settings.maxDur = Math.max(0, Number($('setMaxDur').value) || 0);
  settings.wordTs = $('setWordTs').checked;
  settings.reduceHallu = $('setReduceHallu').checked;
  settings.overwrite = $('setOverwrite').value;
  settings.subBackup = $('setSubBackup').value;
  settings.updateMode = $('setAutoUpdate').value;
  settings.analytics = $('setAnalytics').checked;
  settings.prompt = $('setPrompt').value.trim();
  saveSettings();
  populateProfiles();
  populateTransProfiles();
  applySettingsToUI();
  window.api.send({ cmd: 'set_concurrency', value: Number(settings.concurrency) });
  refreshSubtitleDots();
  maybeApiNotice();
  closeSettings();
  toast('설정을 저장했습니다.', 'ok');
}

/* ---------- 초기화 ---------- */
function init() {
  populateSelects();
  applyTheme();
  pingAnalytics();
  window.api.onEvent(handleEvent);

  $('openFolderBtn').addEventListener('click', openFolder);
  $('generateBtn').addEventListener('click', generate);
  $('translateBtn').addEventListener('click', translateExisting);
  $('themeBtn').addEventListener('click', toggleTheme);
  $('feedbackBtn').addEventListener('click', openFeedback);
  $('feedbackClose').addEventListener('click', closeFeedback);
  $('feedbackCancel').addEventListener('click', closeFeedback);
  $('feedbackSubmit').addEventListener('click', submitFeedback);
  $('feedbackModal').addEventListener('click', (e) => { if (e.target.id === 'feedbackModal') closeFeedback(); });
  $('backendSel').addEventListener('change', maybeApiNotice);

  // 업데이트
  $('checkUpdateBtn').addEventListener('click', () => {
    manualCheck = true;
    toast('업데이트 확인 중…');
    window.api.checkUpdate();
  });
  $('updateAction').addEventListener('click', () => {
    if (updateAct === 'download') {
      window.api.downloadUpdate();
      showUpdateBar('업데이트 다운로드 중…', null, null);
    } else if (updateAct === 'install') {
      window.api.installUpdate();
    }
  });
  $('updateDismiss').addEventListener('click', () => { $('updateBar').hidden = true; });

  // 사용 가이드 버튼
  $('tutClose').addEventListener('click', closeTut);
  $('tutNever').addEventListener('click', neverTut);
  $('tutPrev').addEventListener('click', () => { if (tutPage > 0) { tutPage--; renderTut(); } });
  $('tutNext').addEventListener('click', () => {
    if (tutPage < TUT_PAGES.length - 1) { tutPage++; renderTut(); } else closeTut();
  });
  $('setupRetry').addEventListener('click', () => {
    $('setupMsg').textContent = '다시 시도 중…';
    $('setupRetry').hidden = true;
    window.api.retrySetup();
  });
  $('settingsBtn').addEventListener('click', openSettings);
  $('settingsClose').addEventListener('click', closeSettings);
  $('settingsSave').addEventListener('click', saveSettingsModal);
  $('settingsReset').addEventListener('click', () => {
    if (!confirm('모든 설정을 기본값으로 초기화할까요? (튜닝/번역 프로필·용어집 포함)\n작업 큐와 설치된 런타임에는 영향 없습니다.')) return;
    try { localStorage.removeItem('subgen.settings'); } catch (e) { /* noop */ }
    settings = loadSettings();          // 새로고침 없이 기본값으로 즉시 재적용
    profEditId = null; transEditId = null;
    populateSelects();                  // 셀렉트 재구성 + applySettingsToUI 호출
    applyTheme();
    closeSettings();
    toast('설정을 기본값으로 초기화했습니다.', 'ok');
  });
  $('settingsModal').addEventListener('click', (e) => {
    if (e.target === $('settingsModal')) closeSettings();
  });

  $('selectAll').addEventListener('change', (e) => {
    if (e.target.checked) setSelection(new Set(visibleFileIndices()));
    else setSelection(new Set());
  });

  $('fileSearch').addEventListener('input', (e) => {
    fileFilter = e.target.value || '';
    renderFiles();
  });

  const list = $('fileList');
  list.addEventListener('mousedown', onRowMouseDown);
  list.addEventListener('mouseover', onRowMouseEnter);
  document.addEventListener('mouseup', () => { dragging = false; });

  $('queueList').addEventListener('click', onQueueClick);
  $('cancelAllBtn').addEventListener('click', cancelAll);

  // 드래그&드롭으로 영상 파일 추가
  document.addEventListener('dragover', (e) => {
    e.preventDefault();
    document.body.classList.add('dragover');
  });
  document.addEventListener('dragleave', (e) => {
    if (!e.relatedTarget) document.body.classList.remove('dragover');
  });
  document.addEventListener('drop', onDropFiles);

  for (const id of ['modelSel', 'backendSel', 'langSel', 'targetSel',
    'profileSel', 'transProfileSel', 'fmtSel', 'concInput']) {
    $(id).addEventListener('change', () => { syncSettingsFromBar(); if (id === 'fmtSel') refreshSubtitleDots(); });
  }

  // 튜닝 프로필 편집기
  $('setProfile').addEventListener('change', () => {
    commitProfEditor();
    loadProfEditor($('setProfile').value);
  });
  $('profNewBtn').addEventListener('click', () => {
    commitProfEditor();
    const id = 'tune_' + Date.now();
    settings.tuningProfiles = settings.tuningProfiles || [];
    settings.tuningProfiles.push({ id, name: '새 프로필', text: '' });
    populateProfiles();
    loadProfEditor(id);
  });
  $('profDelBtn').addEventListener('click', () => {
    if (!profEditId) return;
    settings.tuningProfiles = (settings.tuningProfiles || []).filter((p) => p.id !== profEditId);
    if (settings.profileId === profEditId) {
      settings.profileId = (settings.tuningProfiles[0] || {}).id || 'general';
    }
    profEditId = null;
    populateProfiles();
    loadProfEditor((settings.tuningProfiles[0] || {}).id);
  });

  // 번역 프로필(용어집) 편집기
  $('setTransProfile').addEventListener('change', () => {
    commitTransEditor();
    loadTransEditor($('setTransProfile').value);
  });
  $('transNewBtn').addEventListener('click', () => {
    commitTransEditor();
    const id = 'tp_' + Date.now();
    settings.transProfiles = settings.transProfiles || [];
    settings.transProfiles.push({ id, name: '새 프로필', text: '' });
    populateTransProfiles();
    loadTransEditor(id);
  });
  $('transDelBtn').addEventListener('click', () => {
    if (!transEditId) return;
    settings.transProfiles = (settings.transProfiles || []).filter((p) => p.id !== transEditId);
    if (settings.transProfileId === transEditId) settings.transProfileId = '';
    transEditId = null;
    populateTransProfiles();
    loadTransEditor((settings.transProfiles[0] || {}).id);
  });
}

window.addEventListener('DOMContentLoaded', init);
