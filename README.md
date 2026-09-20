<img src='https://i.postimg.cc/pmWWSttG/flamin-galah-logo.png' border='0' alt='flamin-galah-logo'>

# ComfyUI Flamin Galah

Structured filmmaker-style fields → local Ollama → official MiniMax H3 prompt.

## Format

```
integrated_multimodal_description: [Shot 1] ...
overall_soundscape: ...
non_diegetic_music: ...
```

## Setup

1. Ollama running (`http://localhost:11434`)
2. `ollama pull fluffy/l3-8b-stheno-v3.2` (or another uncensored model however results do vary)
3. Copy folder into `ComfyUI/custom_nodes/` and fully restart ComfyUI
4. Delete any old Flamin Galah node from your workflow, then add a fresh one

## Main inputs

- Prompt idea, camera, style, lighting
- duration, dialogue, soundscape, music, extra_details
- ollama_model (dropdown from Ollama)
- optional: ollama_url, temperature, dialogue, soundscape, music, LoRA trigger words

## Notes

`ollama pull fluffy/l3-8b-stheno-v3.2` works well https://ollama.com/fluffy/l3-8b-stheno-v3.2
