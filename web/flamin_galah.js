import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "FlaminGalah.NSFWPromptGenerator",
  async beforeRegisterNodeDef(nodeType, nodeData, app) {
    if (nodeData.name === "FlaminGalahNSFWPromptGenerator") {
      // Soft pink / hot accent so the node is easy to spot
      nodeData.color = "#4a2030";
      nodeData.bgcolor = "#2a1218";
    }
  },
});
