import { app } from "../../scripts/app.js";

const ORANGE = "#e8590c";

const OUTPUT_CHOICES = [
    { label: "Image to Video", value: "Image to Video" },
    { label: "Image to Image", value: "Image to Image" },
];

const DURATION_CHOICES = [4, 5, 6, 7, 8, 9, 10, 12, 15].map((n) => ({
    label: `${n}s`,
    value: n,
}));

const PACK = "Flamin Galah";

function brand(node) {
    if (!node.properties) {
        node.properties = {};
    }
    node.properties.cnr_id = PACK;
    node.properties.aux_id = PACK;
    node.properties.ver = "1.0.9";
    node.cnr_id = PACK;
    relabelBadge(node);
}

function relabelBadge(node) {
    const roots = [node.element, node.domElement, node.htmlElement, node.widgets_host].filter(Boolean);
    for (const root of roots) {
        root.querySelectorAll("span, div, button").forEach((el) => {
            if (el.childNodes.length === 1 && el.textContent.trim() === "comfyui-workflow-encrypt") {
                el.textContent = PACK;
            }
        });
    }
}

function enlargeAction(node) {
    const actionWidget = node.widgets?.find((w) => w.name === "extra_description");
    if (!actionWidget) {
        return;
    }
    actionWidget.inputEl?.style.setProperty("height", "180px", "important");
    actionWidget.inputEl?.style.setProperty("min-height", "180px", "important");
    actionWidget.inputEl?.style.setProperty("resize", "vertical", "important");
    actionWidget.computeSize = function (width) {
        return [width, 190];
    };
}

function hideSource(widget) {
    widget.hidden = true;
    widget.computeSize = () => [0, -4];
    if (widget.element) {
        widget.element.style.display = "none";
    }
    if (widget.inputEl) {
        widget.inputEl.style.display = "none";
        if (widget.inputEl.parentElement) {
            widget.inputEl.parentElement.style.display = "none";
        }
    }
}

function installPills(node, sourceName, choices, options = {}) {
    const source = node.widgets?.find((w) => w.name === sourceName);
    if (!source || source._fgPills) {
        return;
    }
    source._fgPills = true;
    hideSource(source);

    const root = document.createElement("div");
    root.style.display = "flex";
    root.style.flexDirection = options.caption ? "column" : "row";
    root.style.alignItems = options.caption ? "stretch" : "center";
    root.style.gap = "4px";
    root.style.width = "100%";
    root.style.boxSizing = "border-box";
    root.style.padding = "0";
    root.style.margin = "0";
    root.style.userSelect = "none";

    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "6px";
    row.style.width = "100%";

    if (options.caption) {
        const label = document.createElement("div");
        label.textContent = options.caption;
        label.title = options.hint || options.caption;
        label.style.flex = "0 0 auto";
        label.style.height = "16px";
        label.style.lineHeight = "16px";
        label.style.color = "#ffd8a8";
        label.style.font = "700 11px Segoe UI, sans-serif";
        label.style.letterSpacing = "0.06em";
        label.style.textTransform = "uppercase";
        label.style.whiteSpace = "nowrap";
        root.appendChild(label);
    }

    const buttons = choices.map((choice) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = choice.label;
        button.title = options.buttonHint
            ? options.buttonHint(choice)
            : (options.hint || choice.label);
        button.setAttribute("aria-label", button.title);
        button.style.flex = "1 1 0";
        button.style.minWidth = "0";
        button.style.height = "28px";
        button.style.border = "0";
        button.style.borderRadius = "6px";
        button.style.background = "#3a3a3a";
        button.style.color = "#f3f3f3";
        button.style.padding = "0 6px";
        button.style.cursor = "pointer";
        button.style.font = "600 12px Segoe UI, sans-serif";
        button.style.letterSpacing = "0.01em";
        button.addEventListener("pointerdown", (event) => {
            event.stopPropagation();
        });
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            source.value = choice.value;
            if (source.inputEl) {
                source.inputEl.value = String(choice.value);
            }
            source.callback?.(choice.value);
            sync();
            node.setDirtyCanvas?.(true, true);
        });
        row.appendChild(button);
        return button;
    });

    root.appendChild(row);

    function sync() {
        buttons.forEach((button, i) => {
            const on = String(source.value) === String(choices[i].value);
            button.style.background = on ? ORANGE : "#3a3a3a";
            button.style.color = "#fff";
        });
    }
    sync();
    source._fgSync = sync;

    const pillHeight = options.caption ? 50 : 32;
    const dom = node.addDOMWidget(sourceName + "_pills", "fg_pills", root, {
        serialize: false,
        getMinHeight: () => pillHeight,
        getMaxHeight: () => pillHeight,
        getValue: () => source.value,
        setValue() {},
    });
    if (dom) {
        dom.serialize = false;
        const index = node.widgets.indexOf(dom);
        if (index > 0) {
            node.widgets.splice(index, 1);
            node.widgets.unshift(dom);
        }
    }
}


const LOGO_URL = new URL("./flamin-galah-logo.png", import.meta.url).href;
const logoImage = new Image();
logoImage.src = LOGO_URL;

function addLogo(node) {
    if (!node || node._fgLogo) {
        return;
    }
    node._fgLogo = true;

    const draw = node.onDrawForeground;
    node.onDrawForeground = function (ctx) {
        draw?.apply(this, arguments);
        if (!logoImage.complete || !logoImage.naturalWidth) {
            return;
        }
        const size = 16;
        const x = 6;
        const y = -(LiteGraph.NODE_TITLE_HEIGHT || 30) + 6;
        ctx.save();
        ctx.beginPath();
        ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
        ctx.clip();
        ctx.drawImage(logoImage, x, y, size, size);
        ctx.restore();
    };

    const place = () => {
        const roots = [node.element, node.domElement, node.htmlElement].filter(Boolean);
        for (const root of roots) {
            if (root.querySelector?.(".fg-node-logo")) {
                return true;
            }
            const title =
                root.querySelector?.(".node-title") ||
                root.querySelector?.("[class*='title']") ||
                root.querySelector?.("span");
            const img = document.createElement("img");
            img.className = "fg-node-logo";
            img.src = LOGO_URL;
            img.alt = "";
            img.draggable = false;
            img.title = "Flamin Galah";
            img.style.width = "16px";
            img.style.height = "16px";
            img.style.borderRadius = "50%";
            img.style.objectFit = "cover";
            img.style.marginRight = "6px";
            img.style.flex = "0 0 auto";
            img.style.pointerEvents = "none";
            img.style.verticalAlign = "middle";
            if (title?.parentElement) {
                title.parentElement.style.display = "flex";
                title.parentElement.style.alignItems = "center";
                title.parentElement.insertBefore(img, title);
                return true;
            }
            root.prepend(img);
            return true;
        }
        return false;
    };
    if (!place()) {
        setTimeout(place, 40);
        setTimeout(place, 250);
    }
}

function apply(node) {
    if (!node?.comfyClass?.startsWith("FlaminGalah")) {
        return;
    }
    brand(node);
    addLogo(node);
    if (node.comfyClass === "FlaminGalahImageDescriber") {
        installPills(node, "output_mode", OUTPUT_CHOICES);
        node.setSize([Math.max(node.size?.[0] || 0, 280), Math.max(node.size?.[1] || 0, 240)]);
    }
    if (node.comfyClass === "FlaminGalahNSFWPromptGenerator") {
        installPills(node, "duration_seconds", DURATION_CHOICES, {
            caption: "Duration",
            hint: "Sets the shot length written into the prompt: “The shot lasts about N seconds.”",
            buttonHint: (choice) => `Set shot duration to ${choice.label}`,
        });
        enlargeAction(node);
    }
}

function isOurs(node) {
    return Boolean(node?.comfyClass?.startsWith("FlaminGalah"));
}

app.registerExtension({
    name: "FlaminGalah.Nodes",

    async setup() {
        const fix = () => {
            for (const node of app.graph?.nodes || []) {
                if (node?.comfyClass?.startsWith("FlaminGalah")) {
                    brand(node);
                    addLogo(node);
                }
            }
        };
        setInterval(fix, 800);
        fix();
    },

    async loadedGraphNode(node) {
        if (isOurs(node)) {
            brand(node);
            addLogo(node);
        }
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!nodeData?.name?.startsWith("FlaminGalah")) {
            return;
        }
        nodeData.cnr_id = PACK;
        nodeData.python_module = "custom_nodes.ComfyUI-Flamin-Galah";
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            apply(this);
            return result;
        };
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            apply(this);
            const output = this.widgets?.find((w) => w.name === "output_mode");
            const duration = this.widgets?.find((w) => w.name === "duration_seconds");
            output?._fgSync?.();
            duration?._fgSync?.();
            return result;
        };
    },

    async nodeCreated(node) {
        apply(node);
    },
});
