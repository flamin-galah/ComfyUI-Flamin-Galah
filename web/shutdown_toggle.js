import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "FlaminGalah.Shutdown.Toggle",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "ShutdownComputer") return;

        // Leave the native "enabled" boolean widget completely untouched.
        // Renaming it previously caused "Required input is missing: enabled".
        // The native boolean already renders as a proper toggle switch.
    }
});
