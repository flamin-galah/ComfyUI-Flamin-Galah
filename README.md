# 🦩 Flamin Galah NSFW Prompt Generator

Structured filmmaker-style fields → local Ollama → official MiniMax H3 prompt.

**No free-form idea box** — fill action, camera, style, lighting, etc.

## Format

```
integrated_multimodal_description: [Shot 1] ...
overall_soundscape: ...
non_diegetic_music: ...
```

## Setup

1. Ollama running (`http://localhost:11434`)
2. `ollama pull llama3.2` (or another model)
3. Copy folder into `ComfyUI/custom_nodes/` and fully restart ComfyUI
4. Delete any old Flamin Galah node from your graph, then add a fresh one

## Main inputs

- action, camera, style, lighting
- duration, dialogue, soundscape, music, extra_details
- ollama_model (dropdown from Ollama)
- optional: ollama_url, temperature, shot_2_action, negative_notes

## License

MIT
