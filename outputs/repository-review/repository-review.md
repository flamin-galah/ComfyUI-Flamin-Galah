# ComfyUI Flamin Galah — repository review

**Reviewed:** 6 October 2026  
**Repository:** `D:\GitHub\ComfyUI-Flamin-Galah`  
**Branch / HEAD:** `main` / `322809445cbd18b7747e2e26ceb93ae05a7b5b68`  
**Declared version:** `1.0.9`  
**Scope:** Read-only source review, offline regression probes, documentation consistency, and public provider/ComfyUI documentation checks.

## Verdict

**The basic node registration and local Image-to-Video formatting look sound, but several correctness and distribution issues should be addressed before calling this release fully validated.** Eight findings are listed below, plus a frontend-version-dependent compatibility risk. Some behaviors are already disclosed in the README; disclosure does not prevent incorrect downstream prompts.

No tracked project files were changed. The README already had local modifications when review began; they were preserved. Review scripts/results were added under `.work/repository-review/`, and this report is under `outputs/repository-review/`. No commits, package installation, credential inspection, or live provider calls were performed. Git was accessed only with the approved per-command `safe.directory` override; global Git settings were not changed.

## Findings at a glance

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| R1 | High — image correctness | Director returns an apparently successful image-based prompt after vision fails | Mocked generation reproduces the fail-open path |
| R2 | High — registry publishing | Project name contains a space and violates registry ID rules | Metadata inspection and official Comfy specification |
| R3 | Medium | Frontend branding overwrites machine-readable provenance | Mocked extension hooks overwrite supplied IDs and version |
| R4 | Medium | Grok formatter forces live-action and can duplicate `[Shot 1]` | Direct formatter tests |
| R5 | Medium | Director dialogue cleanup misses unlabelled tags and soundscape dialogue | Three direct cleanup tests |
| R6 | Medium | Director can ignore the selected duration | Direct cleanup test: selected 10 seconds, returned 5 |
| R7 | Medium | Local image node treats reasoning text as final model output | Mocked HTTP response with empty content |
| R8 | Low | Ollama fallbacks contain the wrong official Qwen model tag | Offline discovery tests and official model page |

Priority depends on scope: R2 is a publishing/discovery problem, not evidence that copying this folder into `custom_nodes` fails. R1 is a documented design limitation rather than an undocumented exception-handling accident.

## R1 — Image-based Director can succeed without understanding the image

**Locations:** `nodes/node_prompt_director_ollama.py:871–917`, `1013–1060`; fallback construction at `722–740`.

When `_describe_image()` fails, `generate()` prints a warning, clears `image_description`, and keeps `is_i2va=True`. The subsequent writer receives neither image bytes nor a first-frame description. Nevertheless, the output receives the official first-frame reference line and is returned as a normal string. If the writer also fails, the generic text fallback still gets that header.

**Reproduced:** With vision mocked to raise `RuntimeError`, the node returned a structured I2VA prompt. The writer call had `images_b64=None`, and its input contained no `FIRST-FRAME IMAGE DESCRIPTION` block.

**Impact:** Incorrect identity, clothing, pose, composition, or style can pass downstream as a seemingly anchored prompt. A console warning is easy to miss in an automated graph.

**Recommendation:** Fail the image path when first-frame description fails, or expose an explicit user-selected fallback mode with a visible degraded-result signal. Retain the existing text-only fallback for T2VA if that is intended behavior. Merely adding a reference header does not restore image grounding.

## R2 — Invalid registry project name

**Location:** `pyproject.toml:2`.

```toml
name = "Flamin Galah"
```

The [official Comfy Registry specification](https://docs.comfy.org/registry/specifications) permits alphanumerics, hyphens, underscores, and periods in the node ID, but not spaces. The same name also fails the ordinary Python distribution-name character rules. TOML parsing itself succeeds; that is not equivalent to metadata validity.

**Recommendation:** Use the actual valid machine identifier for this pack, for example `flamin-galah` if that is its established published ID. Keep the friendly label in `[tool.comfy].DisplayName`, which already exists. Do not rename an established registry identity without checking publication/migration consequences.

**Limit:** A registry submission or wheel build was not attempted; the finding is based on the explicit naming rules and inspected metadata.

## R3 — Branding overwrites provenance rather than only presentation

**Locations:** `web/flamin_galah.js:15–24`, `269–278`, `289–294`.

`brand()` replaces `properties.cnr_id`, `properties.aux_id`, and `node.cnr_id` with the display text `Flamin Galah`, and replaces `properties.ver` with a hard-coded version. The registration hook also replaces `nodeData.cnr_id` and `nodeData.python_module`. The interval repeats part of this overwrite every 800 ms.

**Reproduced:** A mock node with valid source metadata was rewritten to:

```json
{"cnr_id":"Flamin Galah","aux_id":"Flamin Galah","ver":"1.0.9"}
```

A supplied node definition's registry ID and Python module were also replaced.

**Impact:** Saved workflow provenance no longer accurately reflects the backend or installed package identity. This can interfere with dependency identification and makes alternate installation directory names or future versions harder to diagnose. Actual Manager install/resolve behavior was not exercised.

**Recommendation:** Preserve backend-provided machine identifiers and version. Apply the friendly name through display names, titles, or badges only. If metadata is missing, derive fallback values from authoritative package information rather than assigning a display label to every identifier.

## R4 — Grok formatting contradicts illustrated input and duplicates shot markers

**Locations:** `nodes/node_image_prompt_builder_grok.py:38`, `84–110`.

The formatter always prepends `[Shot 1] Live-action, cinematic,`. It does not preserve the style of an illustration, anime frame, or logo. Its prefix stripper recognizes only a few live-action phrases, so a model-written `[Shot 1]` followed by another style remains in the body.

**Reproduced outputs:**

```text
[Shot 1] Live-action, cinematic, 2D vector illustration of a bird logo.

[Shot 1] Live-action, cinematic, [Shot 1] 2D illustration of a bird.
```

**Recommendation:** Bring the Grok formatter into line with the local image formatter: preserve source-derived style, normalize one leading shot marker, and reject empty visual/soundscape content. Also make the Grok writing instructions explicitly preserve the source style at frame 0.

## R5 — Dialogue controls do not reliably control all dialogue

**Locations:** `nodes/node_prompt_director_ollama.py:573–580`, `612–646`.

Cleanup removes only language-labelled tags matching `<d>[Language] …</d>` from the visual description. It does not remove `<d>…</d>`, even though `_make_dialogue_tag()` intentionally emits that syntax for `dialogue_language="other"`. The model-produced soundscape is not given equivalent cleanup.

**Reproduced:**

- With dialogue disabled, `<d>Hello</d>` survived in the visual field.
- With language set to `other`, model-written `<d>Hello</d>` survived and the same supplied tag was appended again.
- With dialogue disabled and no supplied soundscape override, `<d>[English] Hello</d>` survived in the model's soundscape.

**Recommendation:** Remove all model-generated dialogue tags from all relevant fields before inserting the exact supplied line once. Define handling for untagged model-written speech as well. Add enabled/disabled, labelled/unlabelled, and soundscape regression cases.

## R6 — Selected duration does not override model duration

**Location:** `nodes/node_prompt_director_ollama.py:595–606`.

The cleaner adds the selected duration only when it cannot find a phrase matching `lasts about N seconds`. A model-written duration is left untouched, regardless of the selected value.

**Reproduced:** `duration_seconds=10` plus a writer response containing `The shot lasts about 5 seconds.` returned the five-second clause unchanged.

**Recommendation:** Normalize or replace the recognized duration clause with the selected, clamped value. Cover common variants and avoid appending contradictory durations. The UI hint currently promises that the selected duration is written into the prompt.

## R7 — Reasoning-only Ollama responses become prompt content

**Location:** `nodes/node_image_prompt_builder_ollama.py:293–308`.

When `message.content` is empty, `_call_ollama()` substitutes `message.thinking`. That field is not a final visual description, shot paragraph, or soundscape.

**Reproduced:** A mocked response with empty `content` and `thinking="I need to inspect the image and decide what to describe."` was accepted and returned normally. Any of the three passes can propagate this text to later generation or final formatting.

**Recommendation:** Require non-empty final content. Raise an actionable error or make a bounded retry for reasoning-only responses. Keep reasoning separate from user-facing output.

## R8 — Wrong Qwen tag in both fallback dropdown lists

**Locations:** `nodes/node_prompt_director_ollama.py:128`; `nodes/node_image_prompt_builder_ollama.py:41`.

Both fallback lists contain `qwen2.5-vl`, while the official [Ollama model tag](https://ollama.com/library/qwen2.5vl) is `qwen2.5vl`. The README correctly states this distinction, but the code still offers the incorrect tag when discovery fails.

**Recommendation:** Replace the fallback tag in both modules. The official model page also states an Ollama 0.7.0 requirement; documenting that minimum for this example model would help older installations.

## Frontend compatibility risk — leading nonserialized pills shift positional values

**Location:** `web/flamin_galah.js:155–169`.

`installPills()` sets the new widget's direct `serialize` property to `false`, then moves it to the front of `node.widgets`. This creates a leading skipped slot for full-index workflow serialization.

The upstream [frontend issue #15669](https://github.com/Comfy-Org/ComfyUI_frontend/issues/15669) documents an affected reader that compacted values while the writer retained full widget indices. It was closed through merged PR #15688 on 26 August 2026.

**Offline simulations:**

- On the documented affected reader, a save/load changed `output_mode` to `null` and shifted subsequent values into the wrong widgets.
- On the documented fixed full-index reader, a workflow saved with these pills round-tripped correctly.
- A positional workflow saved without the leading pill slot, such as one made while the extension was absent, shifted values when loaded into the pill-enabled widget layout even using the fixed reader.

**Conclusion:** This is not evidence of a save/load defect in the user's installed frontend. Its version was not inspected. It is a concrete compatibility risk for affected older frontends and different widget-layout histories.

**Recommendation:** Preserve the backend-defined positional layout, add explicit migration support or rely on compatible named-value restoration, and test real save/reload with both pills and earlier workflow layouts. Document a tested frontend version range rather than promising unconditional existing-workflow compatibility.

## Validation performed

| Check group | Result | Boundary |
| --- | --- | --- |
| Python syntax | All five tracked Python files parsed | No bytecode files written |
| JavaScript syntax | ES-module syntax check passed | No real browser execution |
| TOML | Parsed successfully | Registry name is still invalid |
| Package import and registration | Three expected node IDs and `h3_prompt` outputs verified | Image dependencies are absent in this interpreter |
| Input schemas | Required/optional inputs match generation signatures | Ollama discovery mocked |
| Local I2V formatting | Reference line, shot normalization, illustration-style preservation, duplicate-header removal, empty-field rejection passed | Deterministic helper tests |
| Local generation pipeline | Three calls for video, two for image; only first carries image | Calls and image conversion mocked |
| Grok key handling | Missing-key rejection and widget/environment precedence passed | Fake values only; user credentials not read |
| README local image links | All four referenced assets exist | Screenshot contents were not visually checked |
| Offline regression probes | 24 Python probes: 14 pass, 10 unmet assertions | No harness errors |
| Mocked frontend probes | 9 probes: 4 pass, 5 unmet assertions | Includes conditional persistence simulations |

The **33 probes include 18 passing checks and 15 unmet assertions**. These are targeted review probes, not the repository's existing test suite. Multiple assertions cover the same finding; 15 unmet assertions do not mean 15 independent bugs. The scripts completed without harness errors.

### Important limitations

- The available Python 3.14 interpreter has no `torch`, `numpy`, `Pillow`, `pytest`, or `setuptools`. A running ComfyUI instance was not located or launched.
- Real tensor conversion, image resizing, Ollama generation, cloud uploads, model quality, ComfyUI cache behavior, and live browser save/reload were not integration-tested.
- No live xAI/Ollama requests or billable model calls were made.
- Official documentation confirms **`grok-4.7` is valid and accepts image input**. It should not be flagged as an invented model. Access to every other hard-coded dropdown choice was not established for the user's account.
- The Grok path sends full-resolution PNGs without a size guard. The provider currently documents a 20 MiB image limit; this is an additional operational limitation, not a reproduced upload failure.
- The README's existing caveats about duration, dialogue, vision failure, and reasoning fallback accurately acknowledge several findings. There is no tracked automated test suite or CI configuration in this checkout.

## Recommended order of work

1. Prevent ungrounded image-path success and correct the registry identity/provenance handling.
2. Preserve Grok source style and normalize its shot marker.
3. Make dialogue and duration controls deterministic, and reject reasoning-only final output.
4. Correct Qwen fallback tags and add regression tests around the demonstrated cases.
5. Test actual ComfyUI integration, including image conversion and save/reload on supported frontend versions, before declaring the release validated.

## External references

Public references were read on 6 October 2026.

- [Comfy Registry metadata specification](https://docs.comfy.org/registry/specifications)
- [ComfyUI frontend objects and widgets](https://docs.comfy.org/custom-nodes/js/javascript_objects_and_hijacking)
- [Frontend issue #15669: nonserialized-widget positional restore](https://github.com/Comfy-Org/ComfyUI_frontend/issues/15669)
- [Official Ollama Qwen2.5-VL library page](https://ollama.com/library/qwen2.5vl)
- [Official xAI model catalog, including image size limits](https://docs.x.ai/developers/models)
- [Official Grok 4.7 model page](https://docs.x.ai/developers/models/grok-4.7)
- [Official Grok 4.7 announcement](https://x.ai/news/grok-4-7)
