"""
ComfyUI custom node: Flamin Galah NSFW Prompt Generator
Builds structured MiniMax H3 T2VA / I2VA prompts via local Ollama from
filmmaker-style fields (no free-form idea box).

Official format (T2VA):
  integrated_multimodal_description: [Shot 1] ...
  overall_soundscape: ...
  non_diegetic_music: ...

Official format (I2VA):
  For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

  integrated_multimodal_description: [Shot 1] ...
  overall_soundscape: ...
  non_diegetic_music: ...
"""

import json
import urllib.request
import urllib.error
import re
import base64
import io

try:
    import torch
    import numpy as np
    from PIL import Image
except ImportError:
    torch = None
    np = None
    Image = None


OLLAMA_SYSTEM_PROMPT_T2VA = """You are an expert prompt writer for MiniMax H3 video generation.
Your job is to turn structured creative guidance into a complete MiniMax H3 text-to-video (T2VA) prompt.

ALWAYS output EXACTLY this three-field structure and nothing else:

integrated_multimodal_description: [Shot 1] <detailed explicit visual description only – style, lighting, subject, environment, action, camera movement>

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


OLLAMA_SYSTEM_PROMPT_I2VA = """You are an expert prompt writer for MiniMax H3 image-to-video (I2VA) generation.
Your job is to turn a detailed first-frame image description + structured creative guidance into a complete MiniMax H3 I2VA prompt.

ALWAYS output EXACTLY this structure and nothing else (the first-frame instruction line is mandatory):

For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] <start from the image content, then describe the continuous action and camera movement that develops forward from it>

overall_soundscape: <diegetic sounds, breathing, fabric, ambience, dialogue if any>

non_diegetic_music: <music description or N/A>

STRICT RULES FOR I2VA:
- The very first line MUST be exactly:
  For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
- Then a blank line, then the three core fields.
- In [Shot 1] begin by anchoring to the provided image description (appearance, clothing, pose, composition, lighting, environment). Preserve identity, clothing, colors, key objects and spatial relationships from the image.
- Then describe the action onset and continuous development that the user requested (the “change”).
- Write in English except for spoken dialogue and on-screen text.
- Start the first shot with [Shot 1] (no timestamp).
- Describe camera movement clearly (push-in, orbit, tilt, etc.).
- Put spoken dialogue inside <d>[Language] exact words</d> tags.
- Put any visible on-screen text in English double quotes.
- Keep the tone suitable for adult / NSFW content when the user request is adult.
- Be specific about body language, fabric, skin, lighting and atmosphere.
- NEVER put sound descriptions inside the integrated_multimodal_description.
- NEVER put "Avoid" / negative notes inside the integrated_multimodal_description.
- If the user wants no music, set non_diegetic_music: N/A.
- Do not add any extra commentary, markdown, or explanation outside the required structure.

DIALOGUE RULES:
- If dialogue is enabled, it MUST appear in integrated_multimodal_description.
- Clearly identify who is speaking using the supplied dialogue speaker.
- The supplied dialogue must be reproduced exactly.
- Do not paraphrase, translate, shorten, or modify supplied dialogue.
- Format it exactly as <d>[Language] exact words</d>.
- Do not invent additional dialogue.
- If dialogue is disabled, do not generate spoken dialogue.
"""


OLLAMA_VISION_SYSTEM = """You are a precise visual describer for adult / NSFW image-to-video generation.
Describe the supplied image in rich, objective detail suitable as a first-frame anchor.
Include: overall style, lighting, composition, camera angle, subject appearance (body, face, hair, expression), clothing or lack of clothing, pose, body language, environment, key objects, textures (skin, fabric, etc.), and atmosphere.
Be explicit and specific. Do not invent actions that are not visible. Do not add sound. Output only the description paragraph, nothing else."""


def _get_ollama_models(base_url="http://localhost:11434", timeout=2.0):
    fallback = [
        "(Ollama not running – start it and refresh)",
        "llama3.2",
        "llama3.1",
        "llava",
        "llava:13b",
        "qwen2.5-vl",
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


def _tensor_to_base64_png(image_tensor):
    """Convert ComfyUI IMAGE tensor (B,H,W,C) float 0-1 to base64 PNG string."""
    if torch is None or np is None or Image is None:
        raise RuntimeError(
            "torch / numpy / Pillow required for image input. "
            "They are normally present in a ComfyUI environment."
        )

    # Take first image in batch
    img = image_tensor[0]

    if hasattr(img, "cpu"):
        img = img.cpu().numpy()

    # Ensure HWC, float 0-1 → uint8
    if img.dtype != np.uint8:
        img = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)

    if img.shape[-1] == 4:  # RGBA → RGB
        img = img[..., :3]

    pil = Image.fromarray(img)
    buffer = io.BytesIO()
    pil.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


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
                    "chiaroscuro",
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

                "image": ("IMAGE",),

                "vision_model": (model_list, {
                    "default": model_list[0]
                }),

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
        "structured fields → local Ollama → MiniMax H3 T2VA or I2VA format. "
        "Connect an image to enable I2VA (image is described then evolved by your action fields)."
    )

    # ---------------------------------------------------------
    # OLLAMA HELPERS
    # ---------------------------------------------------------

    def _call_ollama(
        self,
        user_content,
        ollama_url,
        ollama_model,
        temperature,
        system_prompt,
        images_b64=None,
    ):

        if (
            ollama_model.startswith("(")
            or not ollama_model.strip()
        ):
            raise RuntimeError(
                "No valid Ollama model selected. Start Ollama, "
                "pull a model (e.g. ollama pull llama3.2 or llava), "
                "then restart ComfyUI."
            )

        url = ollama_url.rstrip("/") + "/api/chat"

        user_msg = {
            "role": "user",
            "content": user_content,
        }
        if images_b64:
            user_msg["images"] = images_b64

        payload = {
            "model": ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                user_msg,
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
                timeout=180
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

    def _describe_image(
        self,
        image_tensor,
        ollama_url,
        vision_model,
        temperature,
    ):
        """Use a vision model to produce a detailed first-frame description."""
        b64 = _tensor_to_base64_png(image_tensor)

        user_content = (
            "Describe this image in rich visual detail. "
            "Focus on style, lighting, composition, subject appearance, "
            "pose, clothing, environment, textures and atmosphere. "
            "Be explicit. Output only the description."
        )

        return self._call_ollama(
            user_content,
            ollama_url,
            vision_model,
            temperature,
            OLLAMA_VISION_SYSTEM,
            images_b64=[b64],
        )

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
        dialogue_language="English",
        is_i2va=False,
    ):

        text = text.strip()

        # Strip any accidental leading instruction if present so we can re-add it cleanly
        text = re.sub(
            r"^For the target video,.*?\n+",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()

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

        core = (
            f"integrated_multimodal_description: "
            f"{description}\n\n\n"
            f"overall_soundscape: "
            f"{final_sound}\n\n\n"
            f"non_diegetic_music: "
            f"{final_music}"
        )

        if is_i2va:
            result = (
                "For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                f"{core}"
            )
        else:
            result = core

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
        lora_tags="",
        image_description=None,
        is_i2va=False,
    ):

        if is_i2va and image_description:
            # Anchor to image then apply the user's requested change
            shot1 = (
                f"[Shot 1] "
                f"{style}, "
                f"{lighting}. "
                f"The scene begins exactly as shown in <Picture 1>: "
                f"{image_description.strip()}. "
                f"A {camera}. "
                f"Then the action develops: {action.strip()}."
            )
        else:
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

        core = (
            f"integrated_multimodal_description: "
            f"{shot1}\n\n\n"
            f"overall_soundscape: "
            f"{soundscape_text}\n\n\n"
            f"non_diegetic_music: "
            f"{music_text}"
        )

        if is_i2va:
            result = (
                "For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                f"{core}"
            )
        else:
            result = core

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
        image=None,
        vision_model=None,
        ollama_url="http://localhost:11434",
        temperature=0.7,
        negative_notes="",
        lora_tags=""
    ):

        is_i2va = image is not None

        # Resolve vision model (fall back to main model if not set)
        if vision_model is None or (
            isinstance(vision_model, str)
            and (vision_model.startswith("(") or not vision_model.strip())
        ):
            vision_model = ollama_model

        image_description = None

        # -----------------------------------------------------
        # I2VA: describe the image first
        # -----------------------------------------------------
        if is_i2va:
            try:
                image_description = self._describe_image(
                    image,
                    ollama_url,
                    vision_model,
                    temperature,
                )
                print(
                    f"[Flamin Galah] Image described "
                    f"({len(image_description)} chars)."
                )
            except Exception as e:
                print(
                    f"[Flamin Galah] Vision describe failed ({e}). "
                    "Falling back to text-only construction."
                )
                image_description = None
                # Keep is_i2va=True so the output still carries the
                # required I2VA header; the fallback will use a generic
                # anchor if description is missing.

        # -----------------------------------------------------
        # Build user content for the prompt writer
        # -----------------------------------------------------

        lines = []

        if is_i2va:
            lines.append("MODE: I2VA (image-to-video)")
            if image_description:
                lines.append(
                    "FIRST-FRAME IMAGE DESCRIPTION "
                    "(use as the exact starting point of Shot 1):"
                )
                lines.append(image_description.strip())
                lines.append("")
                lines.append(
                    "The video must begin with the scene shown in the image "
                    "(preserve identity, clothing, pose, composition, lighting). "
                    "Then develop the following change / action:"
                )
            else:
                lines.append(
                    "An image is provided as the first frame. "
                    "Describe the video starting from that image and then applying the action."
                )
        else:
            lines.append("MODE: T2VA (text-to-video)")

        lines.extend([
            f"Action / change: {action.strip()}",
            f"Camera: {camera}",
            f"Style: {style}",
            f"Lighting: {lighting}",
            f"Duration: about {duration_seconds} seconds",
            (
                f"Soundscape: "
                f"{soundscape.strip() or 'natural ambient sound'}"
            ),
        ])

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

        system_prompt = (
            OLLAMA_SYSTEM_PROMPT_I2VA if is_i2va
            else OLLAMA_SYSTEM_PROMPT_T2VA
        )

        # -----------------------------------------------------
        # Ollama prompt writer
        # -----------------------------------------------------

        try:

            raw = self._call_ollama(
                user_content,
                ollama_url,
                ollama_model,
                temperature,
                system_prompt,
            )

            prompt = self._force_clean_format(
                raw,
                soundscape,
                music,
                lora_tags,
                include_dialogue,
                dialogue_speaker,
                dialogue,
                dialogue_language,
                is_i2va=is_i2va,
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
                lora_tags,
                image_description=image_description,
                is_i2va=is_i2va,
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
