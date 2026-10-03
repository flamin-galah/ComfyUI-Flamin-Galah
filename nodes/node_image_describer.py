"""
ComfyUI custom node: Flamin Galah Image Describer
Uses local Ollama only. A vision model describes the image;
a second local Ollama model writes either an H3 I2V prompt or a I2I paragraph.
"""

import json
import urllib.request
import urllib.error
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


SHOT_OPENER = "[Shot 1] Live-action, cinematic,"

OLLAMA_VISION_SYSTEM = """You are a precise visual describer for image-to-video generation.
Describe the supplied image in rich, objective detail suitable as a first-frame anchor.
Include: overall style, lighting, composition, camera angle, subject appearance (body, face, hair, expression), clothing or lack of clothing, pose, body language, environment, key objects, textures (skin, fabric, etc.), and atmosphere.
Be explicit and specific. Do not invent a different person, outfit, or setting. Do not add sound. Output only the description paragraph, nothing else."""


def _get_ollama_models(base_url="http://localhost:11434", timeout=2.0):
    fallback = [
        "(Ollama not running – start it and refresh)",
        "llava",
        "llava:13b",
        "qwen2.5-vl",
        "llama3.2-vision",
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

            return ["(no models found – run: ollama pull llava)"]

    except Exception:
        return fallback


def _pil_to_base64_png(pil, max_side=1024):
    if pil.mode == "RGBA":
        pil = pil.convert("RGB")
    elif pil.mode not in ("RGB", "L"):
        pil = pil.convert("RGB")
    # Huge frames make Ollama vision calls fail or time out.
    if max(pil.size) > max_side:
        pil = pil.copy()
        pil.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    pil.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _array_to_pil(img):
    if torch is not None and hasattr(img, "cpu"):
        img = img.cpu().numpy()

    if img.dtype != np.uint8:
        img = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)

    if img.ndim == 3 and img.shape[-1] == 4:
        img = img[..., :3]

    return Image.fromarray(img)


def _tensor_to_base64_png(image_tensor):
    """Convert ComfyUI IMAGE tensor (B,H,W,C) float 0-1 to base64 PNG string."""
    if torch is None or np is None or Image is None:
        raise RuntimeError(
            "torch / numpy / Pillow required for image input. "
            "They are normally present in a ComfyUI environment."
        )

    return _pil_to_base64_png(_array_to_pil(image_tensor[0]))


def _strip_redundant_style_prefix(text):
    """Avoid doubling the shot opener if the vision model already starts that way."""
    lowered = text.lstrip().lower()
    prefixes = (
        "[shot 1] live-action, cinematic,",
        "live-action, cinematic,",
        "live-action cinematic,",
        "cinematic, live-action,",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text.lstrip()[len(prefix):].lstrip(" ,")
    return text


PROMPT_WRITER_SYSTEM = """You write MiniMax H3 shot descriptions from a source image description.
Keep identity, clothing, body, setting, lighting, and composition from the source description.
If the user provided an enhancement prompt, incorporate every request as action, camera movement, and continuation after the first frame.
If there is no enhancement prompt, keep the first-frame state and add only a natural slight continuation.
Write one continuous paragraph. No lists, no field labels, no sound, no preamble."""


SOUNDSCAPE_SYSTEM = """You write the H3 overall_soundscape field from a shot description.
Write 1–4 English sentences in one continuous paragraph covering only:
ambient sound; physical action sounds implied by the shot; non-verbal human sounds such as breathing, laughter, or panting.
Do not include dialogue, singing, diegetic music, or non-diegetic music.
Do not use field labels or bullet lists.
Use N/A only if the shot implies complete silence."""


def _format_i2v_output(description, soundscape=""):
    """H3 image-to-video block: three fields, no image-reference header."""
    vision = _strip_redundant_style_prefix((description or "").strip())
    if vision:
        body = f"{SHOT_OPENER} {vision}"
    else:
        body = SHOT_OPENER.rstrip(",")
    sound = (soundscape or "").strip() or "N/A"
    return (
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        "non_diegetic_music: N/A"
    )


def _format_i2i_output(description):
    """Plain text paragraph, no H3 field labels."""
    return _strip_redundant_style_prefix((description or "").strip())


class FlaminGalahImageDescriber:

    @classmethod
    def INPUT_TYPES(cls):
        model_list = _get_ollama_models()

        return {
            "required": {
                "image": ("IMAGE",),
                "output_mode": (["Image to Video", "Image to Image"], {
                    "default": "Image to Video"
                }),
                "extra_description": ("STRING", {
                    "default": "",
                    "multiline": True
                }),
            },
            "optional": {
                "ollama_url": ("STRING", {
                    "default": "http://localhost:11434"
                }),
                "vision_model": (model_list, {
                    "default": model_list[0]
                }),
                "prompt_model": (model_list, {
                    "default": model_list[0]
                }),
                "temperature": ("FLOAT", {
                    "default": 0.2,
                    "min": 0.0,
                    "max": 1.5,
                    "step": 0.05
                }),
                "lora_tag": ("STRING", {
                    "default": "",
                    "multiline": False
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("h3_prompt",)

    FUNCTION = "generate"

    CATEGORY = "prompt/Flamin Galah"

    DESCRIPTION = (
        "Flamin Galah Image Describer – "
        "local Ollama only. Vision model describes the image; "
        "prompt model writes I2V (H3 image-to-video fields) or I2I (plain paragraph)."
    )

    def _call_ollama(
        self,
        user_content,
        ollama_url,
        ollama_model,
        temperature,
        system_prompt,
        images_b64=None,
    ):
        model = (ollama_model or "").strip()
        if model.startswith("(") or not model:
            names = [
                n for n in _get_ollama_models(ollama_url)
                if n and not n.startswith("(")
            ]
            if not names:
                raise RuntimeError(
                    "No Ollama model selected, and none are installed. "
                    "Start Ollama and run: ollama pull llava   or   ollama pull qwen2.5vl"
                )
            model = names[0]

        url = ollama_url.rstrip("/") + "/api/chat"

        user_msg = {
            "role": "user",
            "content": user_content,
        }
        if images_b64:
            user_msg["images"] = images_b64

        payload = {
            "model": model,
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
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8")
                result = json.loads(raw)
                message = result.get("message") or {}
                content = (message.get("content") or "").strip()
                if not content:
                    content = (message.get("thinking") or "").strip()

                if not content:
                    raise RuntimeError(
                        f"Ollama model {model} returned empty content. "
                        "Use a vision model for the image pass (llava, qwen2.5vl, llama3.2-vision)."
                    )

                return content

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            raise RuntimeError(
                f"Ollama rejected the request ({e.code}) for model {model} at {url}. {body}"
            ) from e

        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {ollama_url}. Is it running? {e}"
            ) from e

        except RuntimeError:
            raise

        except Exception as e:
            raise RuntimeError(f"Ollama call failed for model {model}: {e}") from e

    def generate(
        self,
        image,
        output_mode="Image to Video",
        extra_description="",
        ollama_url="http://localhost:11434",
        vision_model="",
        prompt_model="",
        enhance_model="",
        temperature=0.2,
        lora_tag="",
    ):
        if image is None:
            raise RuntimeError("Connect an IMAGE. This node only describes a provided still.")

        frames_b64 = [_tensor_to_base64_png(image)]

        if not prompt_model and enhance_model:
            prompt_model = enhance_model

        if not vision_model or not prompt_model:
            models = _get_ollama_models(ollama_url)
            fallback = models[0] if models else ""
            if not vision_model:
                vision_model = fallback
            if not prompt_model:
                prompt_model = vision_model or fallback

        raw = (output_mode or "Image to Video").strip().lower()
        if raw in ("i2i", "image to image", "t2i", "t2t"):
            mode = "I2I"
        else:
            mode = "I2V"

        extra = (extra_description or "").strip()
        extra_block = extra if extra else "(none)"

        source_description = self._call_ollama(
            (
                "Describe this image in rich visual detail. "
                "Focus on style, lighting, composition, subject appearance, "
                "pose, clothing, environment, textures and atmosphere. "
                "Be explicit. Output only the description."
            ),
            ollama_url,
            vision_model,
            temperature,
            OLLAMA_VISION_SYSTEM,
            images_b64=frames_b64,
        )

        if mode == "I2I":
            rewrite_prompt = (
                "Write a single text prompt paragraph from this source image description.\n\n"
                f"Source image description:\n{source_description}\n\n"
                f"User enhancement prompt:\n{extra_block}\n\n"
                "Keep the visible people, bodies, clothes, and setting from the source. "
                "If the user enhancement prompt is not none, add that action and camera. "
                "Output only the paragraph. No field labels, no sound."
            )
        else:
            rewrite_prompt = (
                "Write the H3 image-to-video shot paragraph from this source image description.\n\n"
                f"Source image description:\n{source_description}\n\n"
                f"User enhancement prompt:\n{extra_block}\n\n"
                "Keep the visible people, bodies, clothes, and setting from the source. "
                "If the user enhancement prompt is not none, add that action, camera, "
                "and continuation after the first frame. "
                "Output only the rewritten paragraph."
            )

        description = self._call_ollama(
            rewrite_prompt,
            ollama_url,
            prompt_model,
            temperature,
            PROMPT_WRITER_SYSTEM,
        )

        if mode == "I2I":
            output = _format_i2i_output(description)
        else:
            soundscape = self._call_ollama(
                (
                    "From this shot description, write overall_soundscape as 1–4 English sentences "
                    "in one paragraph. Include only ambient sound, physical action sounds implied "
                    "by the shot, and non-verbal human sounds. No dialogue, singing, or music.\n\n"
                    f"Shot description:\n{description}\n\n"
                    "Output only the paragraph."
                ),
                ollama_url,
                prompt_model,
                temperature,
                SOUNDSCAPE_SYSTEM,
            )
            output = _format_i2v_output(description, soundscape)

        lora = (lora_tag or "").strip()
        if lora:
            output += f"\n\nLoRA tag: {lora}"
        return (output,)


NODE_CLASS_MAPPINGS = {
    "FlaminGalahImageDescriber": FlaminGalahImageDescriber,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahImageDescriber": "Flamin Galah Image Describer",
}
