"""
ComfyUI custom node: Flamin Galah NSFW Prompt Generator
Builds structured MiniMax H3 T2VA prompts via local Ollama from
filmmaker-style fields (no free-form idea box).

Official format:
  integrated_multimodal_description: [Shot 1] ...
  overall_soundscape: ...
  non_diegetic_music: ...
"""

import json
import urllib.request
import urllib.error
import re


OLLAMA_SYSTEM_PROMPT = """You are an expert prompt writer for MiniMax H3 video generation.
Your job is to turn structured creative guidance into a complete MiniMax H3 text-to-video prompt.

ALWAYS output EXACTLY this three-field structure and nothing else:

integrated_multimodal_description: [Shot 1] <detailed explict visual description only – style, lighting, subject, environment, action, camera movement>

overall_soundscape: <diegetic sounds, breathing, fabric, ambience, dialogue if any>

non_diegetic_music: <music description or N/A>

STRICT RULES:
- Write in English except for spoken dialogue and on-screen text.
- Start the first shot with [Shot 1] (no timestamp).
- Describe camera movement clearly.
- Put spoken dialogue inside <d>[Language] exact words</d> tags.
- Put any visible on-screen text in English double quotes.
- Keep the tone suitable for adult / NSFW content when the user request is adult.
- Be specific about body language, fabric, skin, lighting and atmosphere.
- NEVER put sound descriptions inside the integrated_multimodal_description.
- NEVER put "Avoid" / negative notes inside the integrated_multimodal_description.
- If the user wants no music, set non_diegetic_music: N/A.
- Do not add any extra commentary, markdown, or explanation outside the three fields.

DIALOGUE RULES:
- If dialogue is enabled, it MUST appear in integrated_multimodal_description.
- Clearly identify who is speaking using the supplied dialogue speaker.
- The supplied dialogue must be reproduced exactly.
- Do not paraphrase, translate, shorten, or modify supplied dialogue.
- Format it exactly as <d>[Language] exact words</d>.
- Do not invent additional dialogue.
- If dialogue is disabled, do not generate spoken dialogue.
"""


def _get_ollama_models(base_url="http://localhost:11434", timeout=2.0):
    fallback = [
        "(Ollama not running – start it and refresh)",
        "llama3.2",
        "llama3.1",
        "qwen2.5",
        "mistral",
        "gemma2",
        "phi3",
    ]

    url = base_url.rstrip("/") + "/api/tags"

    try:
        req = urllib.request.Request(url, method="GET")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            models = data.get("models", [])

            names = sorted(
                {
                    m.get("name", "").strip()
                    for m in models
                    if m.get("name")
                },
                key=str.lower,
            )

            if names:
                return names

            return ["(no models found – run: ollama pull llama3.2)"]

    except Exception:
        return fallback


class FlaminGalahNSFWPromptGenerator:

    @classmethod
    def INPUT_TYPES(cls):

        model_list = _get_ollama_models()

        return {
            "required": {

                "action": ("STRING", {
                    "multiline": True,
                    "rows": 6,
                    "default": (
                        "A woman, slim body, huge firm breasts, "
                        "sitting on a chair in an office, "
                        "legs open wide, she looks directly at the "
                        "camera with a seductive expression"
                    )
                }),

                "camera": ([
                    "static wide shot",
                    "point of view",
                    "slow push-in",
                    "tracking shot from the side",
                    "dolly zoom",
                    "handheld following",
                    "low-angle tracking",
                    "aerial descending",
                    "orbit around subject",
                    "static close-up",
                    "pan left to right",
                    "intimate close-up",
                    "slow tilt up the body",
                ], {
                    "default": "static wide shot"
                }),

                "style": ([
                    "live-action cinematic",
                    "photorealistic",
                    "erotic film",
                    "softcore cinematic",
                    "glamour photography",
                    "anime",
                    "cyberpunk",
                    "film noir",
                    "documentary style",
                    "music video",
                ], {
                    "default": "photorealistic"
                }),

                "lighting": ([
                    "soft red practical lights",
                    "warm candlelight",
                    "moody low-key",
                    "neon night with wet reflections",
                    "golden hour soft light",
                    "cool blue moonlight",
                    "high-contrast dramatic",
                    "volumetric fog and shafts of light",
                    "intimate rim lighting",
                ], {
                    "default": "high-contrast dramatic"
                }),

                "duration_seconds": ("INT", {
                    "default": 5,
                    "min": 4,
                    "max": 15,
                    "step": 1
                }),

                "include_dialogue": ("BOOLEAN", {
                    "default": False
                }),

                # NEW: free-text speaker field
                "dialogue_speaker": ("STRING", {
                    "multiline": False,
                    "default": "the woman"
                }),

                "dialogue": ("STRING", {
                    "multiline": False,
                    "default": "Come closer..."
                }),

                "dialogue_language": ([
                    "English",
                    "Chinese",
                    "Japanese",
                    "Korean",
                    "Spanish",
                    "French",
                    "German",
                    "other"
                ], {
                    "default": "English"
                }),

                "soundscape": ("STRING", {
                    "multiline": True,
                    "default": (
                        "soft breathing, fabric sliding, "
                        "distant rain against the window"
                    )
                }),

                "music": ("STRING", {
                    "multiline": False,
                    "default": "N/A"
                }),

                "extra_details": ("STRING", {
                    "multiline": True,
                    "default": (
                        "subtle skin texture, soft shadows, "
                        "intimate atmosphere, shallow depth of field"
                    )
                }),

                "ollama_model": (model_list, {
                    "default": model_list[0]
                }),
            },

            "optional": {

                "ollama_url": ("STRING", {
                    "default": "http://localhost:11434"
                }),

                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 1.5,
                    "step": 0.05
                }),

                "negative_notes": ("STRING", {
                    "multiline": True,
                    "default": (
                        "no text overlays, no logos, no jump cuts, "
                        "no cartoonish proportions, no underage appearance"
                    )
                }),

                "lora_tags": ("STRING", {
                    "multiline": True,
                    "default": ""
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("h3_prompt",)

    FUNCTION = "generate"

    CATEGORY = "prompt/Flamin Galah"

    DESCRIPTION = (
        "Flamin Galah NSFW Prompt Generator – "
        "structured fields → local Ollama → MiniMax H3 format."
    )

    # ---------------------------------------------------------
    # OLLAMA
    # ---------------------------------------------------------

    def _call_ollama(
        self,
        user_content,
        ollama_url,
        ollama_model,
        temperature
    ):

        if (
            ollama_model.startswith("(")
            or not ollama_model.strip()
        ):
            raise RuntimeError(
                "No valid Ollama model selected. Start Ollama, "
                "pull a model (e.g. ollama pull llama3.2), "
                "then restart ComfyUI."
            )

        url = ollama_url.rstrip("/") + "/api/chat"

        payload = {
            "model": ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": OLLAMA_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }

        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )

        try:

            with urllib.request.urlopen(
                req,
                timeout=120
            ) as resp:

                result = json.loads(
                    resp.read().decode("utf-8")
                )

                content = (
                    result
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not content:
                    raise ValueError(
                        "Ollama returned empty content"
                    )

                return content

        except urllib.error.URLError as e:

            raise RuntimeError(
                f"Could not reach Ollama at {ollama_url}. "
                f"Is Ollama running? Error: {e}"
            ) from e

        except Exception as e:

            raise RuntimeError(
                f"Ollama call failed: {e}"
            ) from e

    # ---------------------------------------------------------
    # DIALOGUE
    # ---------------------------------------------------------

    def _make_dialogue_tag(
        self,
        include_dialogue,
        dialogue,
        dialogue_language
    ):

        if not include_dialogue:
            return ""

        if not dialogue or not dialogue.strip():
            return ""

        language = (
            dialogue_language
            if dialogue_language != "other"
            else "English"
        )

        return (
            f"<d>[{language}] "
            f"{dialogue.strip()}</d>"
        )

    # ---------------------------------------------------------
    # FORMAT CLEANUP
    # ---------------------------------------------------------

    def _force_clean_format(
        self,
        text,
        soundscape,
        music,
        lora_tags="",
        include_dialogue=False,
        dialogue_speaker="",
        dialogue="",
        dialogue_language="English"
    ):

        text = text.strip()

        desc_match = re.search(
            r"integrated_multimodal_description:\s*"
            r"(.*?)(?=\n\s*overall_soundscape:"
            r"|\n\s*non_diegetic_music:|$)",
            text,
            re.DOTALL | re.IGNORECASE
        )

        sound_match = re.search(
            r"overall_soundscape:\s*"
            r"(.*?)(?=\n\s*non_diegetic_music:|$)",
            text,
            re.DOTALL | re.IGNORECASE
        )

        music_match = re.search(
            r"non_diegetic_music:\s*(.*)",
            text,
            re.DOTALL | re.IGNORECASE
        )

        if desc_match:
            description = desc_match.group(1).strip()
        else:
            description = text

        # Remove accidental field label
        description = re.sub(
            r"^\s*integrated_multimodal_description:\s*",
            "",
            description,
            flags=re.IGNORECASE
        ).strip()

        # Remove any dialogue generated by Ollama.
        # We insert the exact supplied dialogue ourselves.
        description = re.sub(
            r"<d>\s*\[[^\]]+\]\s*.*?</d>",
            "",
            description,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()

        # -----------------------------------------------------
        # Guarantee [Shot 1]
        # -----------------------------------------------------

        if not re.match(
            r"^\[Shot\s+1\]",
            description,
            flags=re.IGNORECASE
        ):
            description = (
                f"[Shot 1] {description}"
            )

        # -----------------------------------------------------
        # Add exact dialogue
        # -----------------------------------------------------

        dialogue_tag = self._make_dialogue_tag(
            include_dialogue,
            dialogue,
            dialogue_language
        )

        if dialogue_tag:

            speaker = (
                dialogue_speaker.strip()
                if dialogue_speaker
                and dialogue_speaker.strip()
                else "the subject"
            )

            description += (
                f" {speaker.capitalize()} "
                f"speaks clearly: "
                f"{dialogue_tag}."
            )

        # -----------------------------------------------------
        # Soundscape
        # -----------------------------------------------------

        final_sound = (
            soundscape.strip()
            if soundscape
            and soundscape.strip()
            else (
                sound_match.group(1).strip()
                if sound_match
                else "natural ambient sound matching the scene"
            )
        )

        # -----------------------------------------------------
        # Music
        # -----------------------------------------------------

        final_music = (
            music.strip()
            if music
            and music.strip()
            else (
                music_match.group(1).strip()
                if music_match
                else "N/A"
            )
        )

        if final_music.lower() in (
            "none",
            "no music",
            "silent",
            "n/a",
            ""
        ):
            final_music = "N/A"

        result = (
            f"integrated_multimodal_description: "
            f"{description}\n\n\n"
            f"overall_soundscape: "
            f"{final_sound}\n\n\n"
            f"non_diegetic_music: "
            f"{final_music}"
        )

        if lora_tags and lora_tags.strip():
            result = (
                f"{lora_tags.strip()}\n\n"
                f"{result}"
            )

        return result

    # ---------------------------------------------------------
    # FALLBACK
    # ---------------------------------------------------------

    def _build_fallback(
        self,
        action,
        camera,
        style,
        lighting,
        duration_seconds,
        include_dialogue,
        dialogue_speaker,
        dialogue,
        dialogue_language,
        soundscape,
        music,
        extra_details,
        negative_notes="",
        lora_tags=""
    ):

        shot1 = (
            f"[Shot 1] "
            f"{style}, "
            f"{lighting}. "
            f"A {camera}. "
            f"{action.strip()}."
        )

        if extra_details.strip():
            shot1 += (
                f" {extra_details.strip()}."
            )

        dialogue_tag = self._make_dialogue_tag(
            include_dialogue,
            dialogue,
            dialogue_language
        )

        if dialogue_tag:

            speaker = (
                dialogue_speaker.strip()
                if dialogue_speaker
                and dialogue_speaker.strip()
                else "the subject"
            )

            shot1 += (
                f" {speaker.capitalize()} "
                f"speaks clearly: "
                f"{dialogue_tag}."
            )

        soundscape_text = (
            soundscape.strip()
            if soundscape
            and soundscape.strip()
            else "natural ambient sound matching the scene"
        )

        if dialogue_tag:
            soundscape_text += (
                ". Clear spoken dialogue is audible "
                "and lip-synced."
            )

        music_text = (
            music.strip()
            if music
            and music.strip()
            else "N/A"
        )

        if music_text.lower() in (
            "none",
            "no music",
            "silent",
            "n/a",
            ""
        ):
            music_text = "N/A"

        result = (
            f"integrated_multimodal_description: "
            f"{shot1}\n\n\n"
            f"overall_soundscape: "
            f"{soundscape_text}\n\n\n"
            f"non_diegetic_music: "
            f"{music_text}"
        )

        if lora_tags and lora_tags.strip():
            result = (
                f"{lora_tags.strip()}\n\n"
                f"{result}"
            )

        return result

    # ---------------------------------------------------------
    # GENERATE
    # ---------------------------------------------------------

    def generate(
        self,
        action,
        camera,
        style,
        lighting,
        duration_seconds,
        include_dialogue,
        dialogue_speaker,
        dialogue,
        dialogue_language,
        soundscape,
        music,
        extra_details,
        ollama_model,
        ollama_url="http://localhost:11434",
        temperature=0.7,
        negative_notes="",
        lora_tags=""
    ):

        lines = [
            f"Action: {action.strip()}",
            f"Camera: {camera}",
            f"Style: {style}",
            f"Lighting: {lighting}",
            f"Duration: about {duration_seconds} seconds",
            (
                f"Soundscape: "
                f"{soundscape.strip() or 'natural ambient sound'}"
            ),
        ]

        if music.strip() and music.strip().upper() != "N/A":
            lines.append(
                f"Music: {music.strip()}"
            )
        else:
            lines.append(
                "Music: N/A (no non-diegetic score)"
            )

        if extra_details.strip():
            lines.append(
                f"Extra details: "
                f"{extra_details.strip()}"
            )

        # -----------------------------------------------------
        # Dialogue
        # -----------------------------------------------------

        if include_dialogue and dialogue.strip():

            speaker = (
                dialogue_speaker.strip()
                if dialogue_speaker
                and dialogue_speaker.strip()
                else "the subject"
            )

            language = (
                dialogue_language
                if dialogue_language != "other"
                else "English"
            )

            lines.append(
                "DIALOGUE ENABLED."
            )

            lines.append(
                f"Dialogue speaker: {speaker}"
            )

            lines.append(
                f"Dialogue language: {language}"
            )

            lines.append(
                "The following dialogue MUST be included "
                "verbatim in the integrated_multimodal_description:"
            )

            lines.append(
                f"<d>[{language}] {dialogue.strip()}</d>"
            )

        else:

            lines.append(
                "DIALOGUE DISABLED. "
                "Do not generate or invent spoken dialogue."
            )

        # -----------------------------------------------------
        # Negative notes
        # -----------------------------------------------------

        if negative_notes.strip():
            lines.append(
                f"Avoid: {negative_notes.strip()}"
            )

        user_content = "\n".join(lines)

        # -----------------------------------------------------
        # Ollama
        # -----------------------------------------------------

        try:

            raw = self._call_ollama(
                user_content,
                ollama_url,
                ollama_model,
                temperature
            )

            prompt = self._force_clean_format(
                raw,
                soundscape,
                music,
                lora_tags,
                include_dialogue,
                dialogue_speaker,
                dialogue,
                dialogue_language
            )

        except Exception as e:

            print(
                f"[Flamin Galah] Ollama failed "
                f"({e}), using structured fallback."
            )

            prompt = self._build_fallback(
                action,
                camera,
                style,
                lighting,
                duration_seconds,
                include_dialogue,
                dialogue_speaker,
                dialogue,
                dialogue_language,
                soundscape,
                music,
                extra_details,
                negative_notes,
                lora_tags
            )

        return (prompt,)


# -------------------------------------------------------------
# COMFYUI REGISTRATION
# -------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "FlaminGalahNSFWPromptGenerator":
        FlaminGalahNSFWPromptGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahNSFWPromptGenerator":
        "Flamin Galah NSFW Prompt Generator",
}
