import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "FlaminGalahSaveMP4Video";
const DEFAULT_PATTERN = "Video_%date:yyyy-MM-dd%_%counter%";

app.registerExtension({
    name: "FlaminGalah.SaveMP4Video",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);

            const stateWidget = this.addWidget("text", "SaveMP4State", "{}", () => {}, { serialize: false });
            stateWidget.hidden = true;

            const folderWidget = this.addWidget("text", "folder", "", () => {});
            folderWidget.inputEl.placeholder = "ComfyUI output folder (leave empty)";

            const patternWidget = this.addWidget("text", "pattern", DEFAULT_PATTERN, () => {});

            const previewEl = document.createElement("div");
            previewEl.style.cssText = "font-size:12px;color:#aaa;margin:4px 0;white-space:pre-wrap;";
            previewEl.textContent = "Will save as: (run to preview)";
            this.addDOMWidget("will_save", "preview", previewEl);

            const tokens = [
                ["+ Date", "%date:yyyy-MM-dd%"],
                ["+ Counter", "%counter%"],
                ["+ Width", "%width%"],
                ["+ Height", "%height%"],
                ["+ Fps", "%fps%"],
                ["+ Frames", "%frames%"],
                ["+ Duration", "%duration%"],
                ["+ Input", "%input%"],
            ];
            const btnRow = document.createElement("div");
            btnRow.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin:4px 0;";
            tokens.forEach(([label, token]) => {
                const b = document.createElement("button");
                b.textContent = label;
                b.style.cssText = "font-size:11px;padding:2px 6px;";
                b.onclick = () => {
                    patternWidget.value = (patternWidget.value || "") + token;
                    patternWidget.callback?.();
                };
                btnRow.appendChild(b);
            });
            this.addDOMWidget("tokens", "buttons", btnRow);

            const fmtRow = document.createElement("div");
            fmtRow.style.cssText = "display:flex;gap:6px;margin:6px 0;";
            ["MP4", "MP4 HQ"].forEach(fmt => {
                const b = document.createElement("button");
                b.textContent = fmt;
                b.style.cssText = "padding:4px 10px;";
                b.onclick = () => {
                    [...fmtRow.children].forEach(c => c.style.background = "");
                    b.style.background = "#ff6a00";
                };
                fmtRow.appendChild(b);
            });
            this.addDOMWidget("formats", "fmt", fmtRow);

            const modeRow = document.createElement("div");
            modeRow.style.cssText = "display:flex;gap:6px;margin:4px 0;";
            ["Save", "Preview"].forEach(m => {
                const b = document.createElement("button");
                b.textContent = m;
                b.style.cssText = "padding:4px 12px;";
                b.onclick = () => {
                    [...modeRow.children].forEach(c => c.style.background = "");
                    b.style.background = m === "Save" ? "#ff6a00" : "#444";
                };
                modeRow.appendChild(b);
            });
            this.addDOMWidget("mode", "mode", modeRow);

            const player = document.createElement("video");
            player.controls = true;
            player.style.cssText = "width:100%;max-height:200px;background:#111;margin-top:6px;";
            this.addDOMWidget("player", "video", player);

            const orig = this.onSerialize;
            this.onSerialize = (o) => {
                orig?.call(this, o);
                const state = {
                    folder: folderWidget.value || "",
                    pattern: patternWidget.value || DEFAULT_PATTERN,
                    format: "mp4",
                    saveOnRun: true,
                    trimToAudio: false,
                    audioFadeMs: 0,
                    counterDigits: 3,
                };
                stateWidget.value = JSON.stringify(state);
            };

            api.addEventListener("executed", ({ detail }) => {
                if (detail?.node !== this.id) return;
                const vids = detail?.output?.flamin_save_mp4;
                if (vids?.[0]?.path) {
                    previewEl.textContent = "Saved: " + vids[0].path;
                }
            });

            this.setSize([340, 420]);
            return r;
        };
    },
});
