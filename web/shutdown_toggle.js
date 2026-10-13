import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "FlaminGalah.Shutdown.Toggle",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "FlaminGalahShutdown") return;
        // Native enabled boolean is left untouched so the prompt validates.
        // Logo is applied automatically because the class starts with FlaminGalah.
    }
});
