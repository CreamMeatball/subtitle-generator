'use strict';
/**
 * 자동 업데이트 (electron-updater + GitHub Releases).
 *
 * 자동/수동 결정은 렌더러(설정)가 합니다. 메인은 검사·다운로드·설치 트리거만 제공하고,
 * 진행 상황을 이벤트로 렌더러에 보냅니다. autoDownload=false 로 두어, '자동' 모드에서도
 * 렌더러가 update:available 을 받고 다운로드를 시작하게 합니다(설치는 항상 사용자 확인).
 */
let autoUpdater = null;
try { ({ autoUpdater } = require('electron-updater')); } catch (e) { autoUpdater = null; }

function initUpdater(send) {
  if (!autoUpdater) return;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on('checking-for-update', () => send({ type: 'update:checking' }));
  autoUpdater.on('update-available', (info) =>
    send({ type: 'update:available', version: info && info.version }));
  autoUpdater.on('update-not-available', () => send({ type: 'update:none' }));
  autoUpdater.on('download-progress', (p) =>
    send({ type: 'update:progress', percent: Math.round((p && p.percent) || 0) }));
  autoUpdater.on('update-downloaded', (info) =>
    send({ type: 'update:downloaded', version: info && info.version }));
  autoUpdater.on('error', (err) =>
    send({ type: 'update:error', message: String((err && err.message) || err) }));
}

function check() { if (autoUpdater) { try { autoUpdater.checkForUpdates(); } catch (e) { /* noop */ } } }
function download() { if (autoUpdater) { try { autoUpdater.downloadUpdate(); } catch (e) { /* noop */ } } }
function install() { if (autoUpdater) { try { autoUpdater.quitAndInstall(); } catch (e) { /* noop */ } } }

module.exports = { initUpdater, check, download, install, available: !!autoUpdater };
