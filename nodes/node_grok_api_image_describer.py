"""
ComfyUI custom node: Flamin Galah Image Describer
Uses the xAI Grok API to describe a provided image and build an H3 I2VA prompt.
"""

import json
import os
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


GROK_API_URL = "https://api.x.ai/v1/chat/completions"

GROK_MODELS = [
    "grok-4.7",
    "grok-4.6",
    "grok-4.5",
    "grok-4",
    "grok-2-vision-1212",
]

I2VA_FIRST_FRAME_LINE = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)

I2VA_SHOT_OPENER = "[Shot 1] Live-action, cinematic,"

VISION_SYSTEM = """You are a precise visual describer for image-to-video generation.
Describe the supplied image in rich, objective detail suitable as a first-frame anchor.
Include: overall style, lighting, composition, camera angle, subject appearance (body, face, hair, expression), clothing or lack of clothing, pose, body language, environment, key objects, textures (skin, fabric, etc.), and atmosphere.
Be explicit and specific. Do not invent a different person, outfit, or setting. Do not add sound. Output only the description paragraph, nothing else."""

ENHANCE_SYSTEM = """You rewrite first-frame image descriptions into stronger image-to-video shot descriptions.
Keep identity, clothing, body, setting, lighting, and composition from the source description.
Incorporate every request from the user enhancement prompt as action, camera movement, and continuation after the first frame.
Write one continuous paragraph. No lists, no labels, no sound, no preamble."""

SOUNDSCAPE_SYSTEM = """You write the H3 overall_soundscape field from a shot description.
Write 1-4 English sentences in one continuous paragraph covering only:
ambient sound; physical action sounds implied by the shot, including continuation after the first frame; non-verbal human sounds such as breathing, laughter, or panting.
Do not include dialogue, singing, diegetic music, or non-diegetic music.
Do not use field labels or bullet lists.
Use N/A only if the shot implies complete silence."""


def _tensor_to_data_url(image_tensor):
    """Convert ComfyUI IMAGE tensor (B,H,W,C) float 0-1 to a PNG data URL."""
    if torch is None or np is None or Image is None:
        raise RuntimeError(
            "torch / numpy / Pillow required for image input. "
            "They are normally present in a ComfyUI environment."
        )

    img = image_tensor[0]

    if hasattr(img, "cpu"):
        img = img.cpu().numpy()

    if img.dtype != np.uint8:
        img = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)

    if img.shape[-1] == 4:
        img = img[..., :3]

    pil = Image.fromarray(img)
    buffer = io.BytesIO()
    pil.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _strip_redundant_style_prefix(text):
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


def _format_i2va_output(description, soundscape=""):
    vision = _strip_redundant_style_prefix((description or "").strip())
    if vision:
        body = f"{I2VA_SHOT_OPENER} {vision}"
    else:
        body = I2VA_SHOT_OPENER.rstrip(",")
    sound = (soundscape or "").strip()
    return (
        f"{I2VA_FIRST_FRAME_LINE}\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        "non_diegetic_music: N/A"
    )


class FlaminGalahGrokImageDescriber:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "extra_description": ("STRING", {
                    "default": "",
                    "multiline": True
                }),
            },
            "optional": {
                "api_key": ("STRING", {
                    "default": "",
                    "multiline": False
                }),
                "grok_url": ("STRING", {
                    "default": GROK_API_URL
                }),
                "grok_model": (GROK_MODELS, {
                    "default": GROK_MODELS[0]
                }),
                "temperature": ("FLOAT", {
                    "default": 0.2,
                    "min": 0.0,
                    "max": 1.5,
                    "step": 0.05
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("h3_prompt",)

    FUNCTION = "generate"

    CATEGORY = "prompt/Flamin Galah"

    DESCRIPTION = (
        "Flamin Galah Grok Image Describer – "
        "sends the connected image to the xAI Grok API, enhances it with the user prompt, "
        "and returns an H3 I2VA prompt block."
    )

    def _resolve_key(self, api_key):
        key = (api_key or "").strip()
        if key:
            return key
        key = (os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or "").strip()
        if key:
            return key
        raise RuntimeError(
            "No Grok API key. Paste an xAI key into api_key, or set XAI_API_KEY."
        )

    def _call_grok(
        self,
        api_key,
        grok_url,
        model,
        temperature,
        system_prompt,
        user_text,
        image_data_url=None,
    ):
        url = (grok_url or GROK_API_URL).rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"

        if image_data_url:
            user_content = [
                {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}},
                {"type": "text", "text": user_text},
            ]
        else:
            user_content = user_text

        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = (
                    result
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    or ""
                ).strip()
                if not content:
                    raise ValueError("Grok returned empty content")
                return content
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Grok API HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not reach Grok at {url}: {e}") from e

    def generate(
        self,
        image,
        extra_description="",
        api_key="",
        grok_url=GROK_API_URL,
        grok_model="grok-4.7",
        temperature=0.2,
    ):
        if image is None:
            raise RuntimeError("Connect an image. This node only describes a provided image.")

        key = self._resolve_key(api_key)
        data_url = _tensor_to_data_url(image)
        extra = (extra_description or "").strip()
        model = grok_model or GROK_MODELS[0]

        description = self._call_grok(
            key,
            grok_url,
            model,
            temperature,
            VISION_SYSTEM,
            (
                "Describe this image in rich visual detail. "
                "Focus on style, lighting, composition, subject appearance, "
                "pose, clothing, environment, textures and atmosphere. "
                "Be explicit. Output only the description."
            ),
            image_data_url=data_url,
        )

        if extra:
            description = self._call_grok(
                key,
                grok_url,
                model,
                temperature,
                ENHANCE_SYSTEM,
                (
                    "Rewrite the source image description into one stronger first-frame-forward "
                    "shot description.\n\n"
                    f"Source image description:\n{description}\n\n"
                    f"User enhancement prompt (must be fully incorporated):\n{extra}\n\n"
                    "Keep the visible people, bodies, clothes, and setting from the source. "
                    "Add the requested action, camera, and continuation. "
                    "Output only the rewritten paragraph."
                ),
            )

        soundscape = self._call_grok(
            key,
            grok_url,
            model,
            temperature,
            SOUNDSCAPE_SYSTEM,
            (
                "From this shot description, write overall_soundscape as 1-4 English sentences "
                "in one paragraph. Include ambient sound and physical action sounds implied by "
                "the full shot, including any continuation after the first frame, plus non-verbal "
                "human sounds. No dialogue, singing, or music.\n\n"
                f"Shot description:\n{description}\n\n"
                "Output only the paragraph."
            ),
        )

        return (_format_i2va_output(description, soundscape),)


NODE_CLASS_MAPPINGS = {
    "FlaminGalahGrokImageDescriber": FlaminGalahGrokImageDescriber,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahGrokImageDescriber": "Flamin Galah Grok Image Describer",
}
