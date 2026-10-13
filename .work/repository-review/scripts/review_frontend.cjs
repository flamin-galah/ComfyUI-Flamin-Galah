// Offline extension probes using lightweight DOM/ComfyUI mocks, not a real browser.
// Legacy and fixed restore loops model the behavior documented in frontend #15669.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../..');
const checks = [];
let extension;
function element(tag) {
  return {
    tag, style: { setProperty(key, value) { this[key] = value; } }, children: [], events: {},
    appendChild(child) { this.children.push(child); child.parentElement = this; },
    setAttribute(key, value) { this[key] = value; },
    addEventListener(type, fn) { this.events[type] = fn; },
    querySelectorAll() { return []; }, querySelector() { return null; }
  };
}
const context = vm.createContext({
  app: { registerExtension(value) { extension = value; }, graph: { nodes: [] } },
  document: { createElement: element }, URL, console,
  Image: class { complete = false; naturalWidth = 0; }, LiteGraph: { NODE_TITLE_HEIGHT: 30 },
  setTimeout() {}, setInterval() {}
});
let source = fs.readFileSync(path.join(root, 'web/flamin_galah.js'), 'utf8');
source = source.replace(/^import[^\n]+\n/, '').replace(/import\.meta\.url/g, JSON.stringify('file:///mock/web/flamin_galah.js'));
vm.runInContext(source, context, { filename: 'flamin_galah.js' });

function imageNode() {
  const values = [
    ['output_mode', 'Image to Video'], ['extra_description', 'A bird tilts its head'],
    ['ollama_url', 'http://localhost:11434'], ['vision_model', 'qwen2.5vl'],
    ['prompt_model', 'llama3.2'], ['temperature', 0.2], ['lora_tag', '']
  ];
  return {
    comfyClass: 'FlaminGalahImageDescriber',
    properties: { cnr_id: 'flamin-galah', aux_id: 'flamin-galah/ComfyUI-Flamin-Galah', ver: '9.9.9' },
    widgets: values.map(([name, value]) => ({ name, value, options: {} })), size: [280, 240],
    addDOMWidget(name, type, el, options) {
      const widget = { name, type, element: el, options, value: options.getValue() };
      this.widgets.push(widget); return widget;
    },
    setSize(value) { this.size = value; }, setDirtyCanvas() { this.dirty = true; }
  };
}
function check(name, fn) {
  try { const evidence = fn(); checks.push({ name, status: 'PASS', evidence: evidence || '' }); }
  catch (err) { checks.push({ name, status: err instanceof assert.AssertionError ? 'FAIL' : 'ERROR', evidence: err.message }); }
}
function serialize(node) {
  const values = [];
  node.widgets.forEach((w, i) => { if (w.serialize !== false) values[i] = w.value; });
  return JSON.parse(JSON.stringify(values));
}
function legacyRestore(node, values) {
  let i = 0;
  for (const w of node.widgets) {
    if (w.serialize === false) continue;
    if (i >= values.length) break;
    w.value = values[i++];
  }
}
function fixedRestore(node, values) {
  node.widgets.forEach((w, i) => { if (w.serialize !== false && i < values.length) w.value = values[i]; });
}

async function main() {
  check('Extension registration', () => { assert.equal(extension.name, 'FlaminGalah.Nodes'); return extension.name; });
  const branded = imageNode(); await extension.nodeCreated(branded);
  check('Branding preserves backend registry ID', () => {
    assert.equal(branded.properties.cnr_id, 'flamin-galah', JSON.stringify(branded.properties));
  });
  check('Branding preserves backend repository identifier and version', () => {
    assert.equal(branded.properties.aux_id, 'flamin-galah/ComfyUI-Flamin-Galah', JSON.stringify(branded.properties));
    assert.equal(branded.properties.ver, '9.9.9', JSON.stringify(branded.properties));
  });
  const type = function () {};
  const definition = { name: 'FlaminGalahImageDescriber', cnr_id: 'flamin-galah', python_module: 'custom_nodes.actual_install_name' };
  await extension.beforeRegisterNodeDef(type, definition);
  check('Node-definition hook preserves source metadata', () => {
    assert.equal(definition.cnr_id, 'flamin-galah', JSON.stringify(definition));
    assert.equal(definition.python_module, 'custom_nodes.actual_install_name', JSON.stringify(definition));
  });
  check('Pills retain source widget and serialize no UI-only value', () => {
    assert.equal(branded.widgets[0].name, 'output_mode_pills');
    assert.equal(branded.widgets[0].serialize, false);
    assert.ok(branded.widgets.find(w => w.name === 'output_mode').hidden);
    return 'Leading UI-only widget, original source widget retained';
  });
  check('Pill click updates source value and canvas', () => {
    const pill = branded.widgets[0];
    const button = pill.element.children[0].children[1];
    button.events.click({ preventDefault() {}, stopPropagation() {} });
    assert.equal(branded.widgets.find(w => w.name === 'output_mode').value, 'Image to Image');
    assert.equal(branded.dirty, true);
    return 'Image to Image pill updates the underlying widget';
  });
  check('Legacy frontend indexed save/load preserves values (version-dependent)', () => {
    const values = serialize(branded);
    const reader = imageNode();
    // Calling extension.apply synchronously through the registered node hook adds the pill.
    type.prototype.onNodeCreated.call(reader);
    legacyRestore(reader, values);
    assert.equal(reader.widgets.find(w => w.name === 'output_mode').value, 'Image to Image',
      'Serialized=' + JSON.stringify(values) + '; restored=' + JSON.stringify(reader.widgets.map(w => [w.name, w.value])));
  });
  check('Fixed full-index frontend save/load preserves values (simulation)', () => {
    const values = serialize(branded);
    const reader = imageNode(); type.prototype.onNodeCreated.call(reader);
    fixedRestore(reader, values);
    assert.equal(reader.widgets.find(w => w.name === 'output_mode').value, 'Image to Image');
    assert.equal(reader.widgets.find(w => w.name === 'extra_description').value, 'A bird tilts its head');
    return 'Current documented full-index restore loop preserves values';
  });
  check('Indexed workflow made without pills loads into pill UI (compatibility risk)', () => {
    const plain = imageNode();
    const values = serialize(plain);
    const reader = imageNode(); type.prototype.onNodeCreated.call(reader);
    fixedRestore(reader, values);
    assert.equal(reader.widgets.find(w => w.name === 'output_mode').value, 'Image to Video',
      'Workflow without leading pill slot restores output_mode=' + JSON.stringify(reader.widgets.find(w => w.name === 'output_mode').value));
  });
  const summary = Object.fromEntries(['PASS', 'FAIL', 'ERROR'].map(state => [state, checks.filter(c => c.status === state).length]));
  const dest = path.join(root, '.work/repository-review/results/frontend_checks.json');
  fs.writeFileSync(dest, JSON.stringify({ summary, environment: 'Mock DOM and ComfyUI; restore algorithms simulated from published upstream issue', checks }, null, 2));
  for (const item of checks) { console.log(item.status + ': ' + item.name); if (item.status !== 'PASS') console.log('  ' + item.evidence); }
  console.log('SUMMARY:', summary); console.log('RESULT FILE:', dest);
  if (summary.ERROR) process.exitCode = 2;
}
main().catch(err => { console.error(err); process.exitCode = 2; });
