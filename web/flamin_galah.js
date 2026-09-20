import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "FlaminGalah.NSFWPromptGenerator",

    async nodeCreated(node) {
        if (node.comfyClass !== "FlaminGalahNSFWPromptGenerator") {
            return;
        }

        // Find the Action widget
        const actionWidget = node.widgets?.find(
            (w) => w.name === "action"
        );

        if (!actionWidget) {
            return;
        }

        // Force Action widget to be a large multiline text box
        actionWidget.inputEl?.style.setProperty(
            "height",
            "180px",
            "important"
        );

        actionWidget.inputEl?.style.setProperty(
            "min-height",
            "180px",
            "important"
        );

        actionWidget.inputEl?.style.setProperty(
            "resize",
            "vertical",
            "important"
        );

        // ComfyUI/LiteGraph widget sizing
        actionWidget.computeSize = function(width) {
            return [width, 190];
        };

        // Give the node enough vertical space
        node.setSize([
            Math.max(node.size[0], 350),
            Math.max(node.size[1], 650)
        ]);

        node.setDirtyCanvas(true, true);
    },
});