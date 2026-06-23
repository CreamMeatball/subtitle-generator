'use strict';
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('api', {
  openFolder: () => ipcRenderer.invoke('dialog:openFolder'),
  hasSubtitle: (videoPath, fmt) => ipcRenderer.invoke('fs:hasSubtitle', videoPath, fmt),
  findSubtitle: (videoPath) => ipcRenderer.invoke('fs:findSubtitle', videoPath),
  send: (cmd) => ipcRenderer.send('engine:cmd', cmd),
  thumb: (videoPath) => ipcRenderer.invoke('thumb:get', videoPath),
  showInFolder: (p) => ipcRenderer.send('shell:showItem', p),
  retrySetup: () => ipcRenderer.send('setup:retry'),
  reinstallRuntime: () => ipcRenderer.invoke('runtime:reinstall'),
  openExternal: (url) => ipcRenderer.send('shell:openExternal', url),
  checkUpdate: () => ipcRenderer.send('update:check'),
  downloadUpdate: () => ipcRenderer.send('update:download'),
  installUpdate: () => ipcRenderer.send('update:install'),
  // 드래그&드롭된 File의 실제 경로(Electron 30+)
  pathForFile: (file) => {
    try { return webUtils.getPathForFile(file); }
    catch (e) { return (file && file.path) || ''; }
  },
  onEvent: (cb) => ipcRenderer.on('engine:event', (e, ev) => cb(ev)),
});
