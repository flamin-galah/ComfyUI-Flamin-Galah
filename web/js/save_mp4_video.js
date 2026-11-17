// Flamin Galah Save MP4 Video – frontend
// Place this file at: web/js/save_mp4_video.js

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE = "FlaminGalahSaveMP4Video";

app.registerExtension({
    name: "FlaminGalah.SaveMP4",

    async nodeCreated(node) {
        if (node.comfyClass !== NODE) return;

        // Hidden state that gets sent to Python
        const stateW = node.addWidget("text", "SaveMP4State", "{}", () => {}, { serialize: false });
        stateW.hidden = true;

        // Folder
        const folderW = node.addWidget("text", "folder", "", () => {});
        if (folderW.inputEl) folderW.inputEl.placeholder = "leave empty = ComfyUI output";

        // Pattern
        const patternW = node.addWidget("text", "pattern", "Video_%date:yyyy-MM-dd%_%counter%", () => {});

        // Token buttons
        const btnDiv = document.createElement("div");
        btnDiv.style.cssText = "display:flex;flex-wrap:wrap;gap:3px;padding:4px 0;";
        const tokens = [
            ["Date", "%date:yyyy-MM-dd%"],
            ["Counter", "%counter%"],
            ["Width", "%width%"],
            ["Height", "%height%"],
            ["Fps", "%fps%"],
            ["Frames", "%frames%"],
            ["Duration", "%duration%"],
            ["Input", "%input%"],
        ];
        tokens.forEach(([label, tok]) => {
            const b = document.createElement("button");
            b.textContent = "+" + label;
            b.style.cssText = "font-size:10px;padding:2px 5px;cursor:pointer;";
            b.onclick = () => {
                patternW.value = (patternW.value || "") + tok;
                if (patternW.callback) patternW.callback();
            };
            btnDiv.appendChild(b);
        });
        node.addDOMWidget("tokens", "html", btnDiv);

        // Format buttons
        const fmtDiv = document.createElement("div");
        fmtDiv.style.cssText = "display:flex;gap:6px;padding:4px 0;";
        ["MP4", "MP4 HQ"].forEach(name => {
            const b = document.createElement("button");
            b.textContent = name;
            b.style.cssText = "padding:3px 10px;cursor:pointer;";
            b.onclick = () => {
                [...fmtDiv.querySelectorAll("button")].forEach(x => x.style.background = "");
                b.style.background = "#ff6600";
            };
            fmtDiv.appendChild(b);
        });
        node.addDOMWidget("formats", "html", fmtDiv);

        // Player
        const video = document.createElement("video");
        video.controls = true;
        video.style.cssText = "width:100%;background:#111;margin-top:4px;";
        node.addDOMWidget("player", "html", video);

        // Save state on prompt
        const oldSerialize = node.onSerialize;
        node.onSerialize = function (o) {
            if (oldSerialize) oldSerialize.call(this, o);
            stateW.value = JSON.stringify({
                folder: folderW.value || "",
                pattern: patternW.value || "Video_%counter%",
                format: "mp4",
                saveOnRun: true,
            });
        };

        node.setSize([320, 380]);
    },
});
