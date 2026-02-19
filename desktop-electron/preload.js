const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mustarrdDesktop", {
  async getLaunchOnStartup() {
    return ipcRenderer.invoke("desktop:get-launch-on-startup");
  },
  async setLaunchOnStartup(enabled) {
    return ipcRenderer.invoke("desktop:set-launch-on-startup", Boolean(enabled));
  },
  async openFileLocation(filePath) {
    return ipcRenderer.invoke("desktop:open-file-location", filePath);
  },
  async playFile(filePath) {
    return ipcRenderer.invoke("desktop:play-file", filePath);
  }
});
