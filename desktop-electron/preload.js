const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mustarrdDesktop", {
  async getLaunchOnStartup() {
    return ipcRenderer.invoke("desktop:get-launch-on-startup");
  },
  async setLaunchOnStartup(enabled) {
    return ipcRenderer.invoke("desktop:set-launch-on-startup", Boolean(enabled));
  }
});
