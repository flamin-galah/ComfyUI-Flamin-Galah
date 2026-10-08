"""
ComfyUI custom node: Flamin Galah Image Prompt Builder (Grok)
Uses the xAI Grok API to build H3 I2VA prompts from an image or T2VA prompts from text.
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

VISION_SYSTEM = """You are a precise visual describer for image-to-video generation.
Describe the supplied image in rich, objective detail suitable as a first-frame anchor.
Include: overall style, lighting, composition, camera angle, subject appearance (body, face, hair, expression), clothing or lack of clothing, pose, body language, environment, key objects, textures (skin, fabric, etc.), and atmosphere.
Be explicit and specific. Do not invent a different person, outfit, or setting. Do not add sound. Output only the description paragraph, nothing else."""

ENHANCE_SYSTEM = """You rewrite first-frame image descriptions into stronger image-to-video shot descriptions.
Keep identity, clothing, body, setting, lighting, composition, and visual style from the source description. Do not turn an illustration, animation, logo, or other stylized image into live-action.
Incorporate every request from the user enhancement prompt as action, camera movement, and continuation after the first frame.
If the user supplies spoken lines or lyrics, include them. Do not invent dialogue or singing. On the first vocalization assign a stable speaker id such as (S1). Put identity, delivery, and the id outside the tag. Inside the tag put only the language label and the verbatim line, for example: The woman with a low voice (S1) says: <d>[English] exact user line.</d>
Diegetic music the characters can hear also belongs in this paragraph. Do not write overall_soundscape or non_diegetic_music.
Write one continuous paragraph beginning with [Shot 1]. No lists, no field labels, no preamble."""

SOUNDSCAPE_SYSTEM = """You write the H3 overall_soundscape field from a shot description.
Write 1-4 English sentences in one continuous paragraph covering only:
ambient sound; physical action sounds implied by the shot, including continuation after the first frame; non-verbal human sounds such as breathing, laughter, or panting.
Do not include dialogue, singing, diegetic music, or non-diegetic music.
Do not use field labels or bullet lists.
Use N/A only when the user explicitly requests complete silence throughout the video. A quiet or static scene alone is not a silence request."""


MUSIC_SYSTEM = """You write the H3 non_diegetic_music field.
Write 1-3 English sentences describing background music the characters cannot hear. Cover instrumentation, tempo, rhythm, and dynamic change. Do not use abstract mood words or explain the emotional purpose of the score.
If the user names a score, follow that. If the user explicitly requests no music, output N/A. Otherwise write a concrete score that fits the shot's pace and setting.
Do not repeat dialogue, singing, or diegetic music. No field label, no bullet list."""


REF2VA_SYSTEM = """You write a MiniMax H3 full-reference (Ref2VA) prompt from two reference images.
The images are character or subject references, not first and last frames.
Picture 1, the first attached image, is the source of <Subject 1>, the primary subject.
Picture 2, the second attached image, is the source of <Subject 2>, the secondary subject.
Do not create standalone <Picture N> lines. Cite each image only inside its subject definition, because these images define identity rather than a concrete target frame.
Output exactly these six sections, in this order, with these headers and no other preamble:

subject_definitions:
<Subject 1> is the primary subject shown in Picture 1, with the visible identity, face, hair, body, clothing, and distinctive features.
<Subject 2> is the secondary subject shown in Picture 2, with the visible identity, face, hair, body, clothing, and distinctive features.

summary:
[reference generation] One English paragraph describing the target video and how <Subject 1> and <Subject 2> are used. Do not introduce labels that were not defined.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - identity, facial features, clothing, and visual characteristics from Picture 1 are retained.
<Subject 2> (appears in [Shot 1]): fully_preserved - identity, facial features, clothing, and visual characteristics from Picture 2 are retained.

detailed_description:
One detailed English playback description, normally 350-500 words unless the user supplied a short dialogue timeline. Begin with the visual style. Then write [Shot 1] and later shots as [Shot N] At MM:SS.mmm. On first appearance, restate each subject's referenced appearance, position, and action. Describe interaction, environment, lighting, time of day, camera framing, movement, lens feel, focus, body motion, expression, and clothing or hair motion. Include user-supplied dialogue only, using (S1) and (S2) and <d>[English] verbatim line.</d>. Do not invent dialogue.

overall_soundscape:
1-4 English sentences of ambient sound, physical action sounds, and non-verbal human sounds. No dialogue or music. Use N/A only if the user explicitly requests complete silence.

non_diegetic_music:
1-3 English sentences of audience-only score, covering instrumentation, tempo, rhythm, and dynamics. Use N/A only if the user requests no music.

Preserve both identities. Do not merge the two people into one. Follow the user directions for action and interaction. Write in English except for verbatim dialogue and visible text.
"""


TEXT_TO_VIDEO_SYSTEM = """You write a MiniMax H3 text-to-video shot description from the user's scene directions.
No reference image is supplied. Build the scene from the user's text; do not refer to an uploaded image, a first-frame reference, or <Picture 1>.
Write one continuous English paragraph beginning with [Shot 1]. Establish the requested visual style, subject appearance, composition, setting, and lighting before developing the action, camera motion, and result or reaction.
Follow all supplied scene directions. Preserve the requested style, including animation or illustration; if no style is specified, choose a suitable cinematic style.
Keep requested duration and camera direction in the description when supplied. Keep visible text verbatim in English double quotes.
If the user supplies spoken lines or lyrics, include them. Do not invent dialogue or singing. On the first vocalization assign a stable speaker id such as (S1). Put identity, delivery, and the id outside the tag. Inside the tag put only the language label and the verbatim line, for example: The woman with a low voice (S1) says: <d>[English] exact user line.</d>
Diegetic music the characters can hear also belongs in this paragraph.
Output only the shot paragraph. No field labels, alignment instruction, lists, soundscape, non-diegetic music, or preamble."""

TEXT_SOUNDSCAPE_SYSTEM = """You write the H3 overall_soundscape field for a text-to-video shot.
Write 1-4 English sentences in one continuous paragraph covering only ambient sound, physical action sounds, and non-verbal human sounds consistent with the scene and user directions.
Do not include dialogue, singing, diegetic music, non-diegetic music, field labels, or bullet lists.
Use N/A only when the user explicitly requests complete silence throughout the video. A quiet or static scene alone is not a silence request."""


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


def _format_shot_body(description):
    vision = (description or "").strip()
    if not vision:
        raise RuntimeError("Grok returned an empty shot description.")
    if vision.lower().startswith("[shot 1]"):
        return "[Shot 1]" + vision[len("[Shot 1]"):]
    return f"[Shot 1] {vision}"


def _format_i2va_output(description, soundscape="", music=""):
    body = _format_shot_body(description)
    sound = (soundscape or "").strip()
    if not sound:
        raise RuntimeError("Grok returned an empty image-to-video soundscape.")
    score = (music or "").strip() or "N/A"
    return (
        f"{I2VA_FIRST_FRAME_LINE}\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        f"non_diegetic_music: {score}"
    )


def _format_t2va_output(description, soundscape="", music=""):
    """Text-to-video has three fields and no image-alignment instruction."""
    body = _format_shot_body(description)
    sound = (soundscape or "").strip()
    if not sound:
        raise RuntimeError("Grok returned an empty text-to-video soundscape.")
    score = (music or "").strip() or "N/A"
    return (
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        f"non_diegetic_music: {score}"
    )



_REF2VA_HEADERS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


def _format_ref2va_output(raw):
    """Keep the official six-section order and drop a model preamble."""
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("Grok returned an empty reference-to-video prompt.")
    lowered = text.lower()
    positions = []
    for header in _REF2VA_HEADERS:
        marker = header + ":"
        index = lowered.find(marker)
        if index < 0:
            raise RuntimeError(f"Grok reference prompt is missing {header}:")
        positions.append((index, header))
    positions.sort()
    chunks = {header: "" for header in _REF2VA_HEADERS}
    for pos, (index, header) in enumerate(positions):
        start = index + len(header) + 1
        end = positions[pos + 1][0] if pos + 1 < len(positions) else len(text)
        chunks[header] = text[start:end].strip()
    missing = [header for header in _REF2VA_HEADERS if not chunks[header]]
    if missing:
        raise RuntimeError("Grok reference prompt has empty sections: " + ", ".join(missing))
    return "\n\n".join(f"{header}:\n{chunks[header]}" for header in _REF2VA_HEADERS)


class FlaminGalahGrokImageDescriber:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "extra_description": ("STRING", {
                    "default": "",
                    "multiline": True
                }),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
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
        "Flamin Galah Image Prompt Builder (Grok) – "
        "runs with image_1, image_2, both, or neither. "
        "One image builds an H3 I2VA prompt. Both images build an H3 Ref2VA prompt. "
        "No image builds a T2VA prompt from extra_description."
    )


    def _generate_ref2va(self, image, image_2, extra, api_key, grok_url, grok_model, temperature):
        key = self._resolve_key(api_key)
        model = grok_model or GROK_MODELS[0]
        directions = extra or "(none — invent a short interaction that keeps both identities)"
        raw = self._call_grok(
            key,
            grok_url,
            model,
            temperature,
            REF2VA_SYSTEM,
            (
                "The first image is Picture 1, the primary subject reference. "
                "The second image is Picture 2, the secondary subject reference. "
                "Write the six-section H3 Ref2VA prompt. "
                "Do not use standalone Picture lines, and do not use [SUBJECTS], [ACTION], "
                "[SCENE], [CAMERA], [MOTION], [AUDIO], or [CONTINUITY] headings.\n\n"
                f"User directions:\n{directions}\n\n"
                "Output only the six sections."
            ),
            image_data_urls=[
                _tensor_to_data_url(image),
                _tensor_to_data_url(image_2),
            ],
        )
        return _format_ref2va_output(raw)

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
        image_data_urls=None,
    ):
        url = (grok_url or GROK_API_URL).rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"

        urls = list(image_data_urls or [])
        if image_data_url:
            urls.insert(0, image_data_url)
        if urls:
            user_content = [
                {"type": "image_url", "image_url": {"url": item, "detail": "high"}}
                for item in urls
            ]
            user_content.append({"type": "text", "text": user_text})
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
        extra_description="",
        image_1=None,
        image_2=None,
        api_key="",
        grok_url=GROK_API_URL,
        grok_model="grok-4.7",
        temperature=0.2,
    ):
        extra = (extra_description or "").strip()
        if image_1 is not None and getattr(image_1, "shape", (1,))[0] == 0:
            image_1 = None
        if image_2 is not None and getattr(image_2, "shape", (1,))[0] == 0:
            image_2 = None
        if image_1 is None and image_2 is None and not extra:
            raise RuntimeError(
                "Connect image_1, image_2, or both, or enter scene directions in extra_description. "
                "Text-to-video requires a non-empty description."
            )
        if image_1 is not None and image_2 is not None:
            return (self._generate_ref2va(
                image_1, image_2, extra, api_key, grok_url, grok_model, temperature
            ),)

        key = self._resolve_key(api_key)
        model = grok_model or GROK_MODELS[0]
        single_image = image_1 if image_1 is not None else image_2

        if single_image is None:
            description = self._call_grok(
                key,
                grok_url,
                model,
                temperature,
                TEXT_TO_VIDEO_SYSTEM,
                (
                    "Write one H3 text-to-video shot paragraph from these scene directions. "
                    "No image is supplied.\n\n"
                    f"Scene directions:\n{extra}\n\n"
                    "Output only the shot paragraph."
                ),
            )
            soundscape = self._call_grok(
                key,
                grok_url,
                model,
                temperature,
                TEXT_SOUNDSCAPE_SYSTEM,
                (
                    "From this shot description, write overall_soundscape as 1-4 English sentences "
                    "in one paragraph. Include ambient sound, physical action sounds, and "
                    "non-verbal human sounds. No dialogue, singing, or music. "
                    "Use N/A only if the user explicitly requests complete silence.\n\n"
                    f"Shot description:\n{description}\n\n"
                    f"User directions:\n{extra}\n\n"
                    "Output only the soundscape paragraph."
                ),
            )
            music = self._call_grok(
                key,
                grok_url,
                model,
                temperature,
                MUSIC_SYSTEM,
                (
                    "From this shot description, write non_diegetic_music as 1-3 English sentences. "
                    "Describe instrumentation, tempo, rhythm, and dynamic change. "
                    "No mood words. Output N/A only if the user explicitly requests no music.\n\n"
                    f"Shot description:\n{description}\n\n"
                    f"User directions:\n{extra}\n\n"
                    "Output only the music paragraph or N/A."
                ),
            )
            return (_format_t2va_output(description, soundscape, music),)

        data_url = _tensor_to_data_url(single_image)
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
        music = self._call_grok(
            key,
            grok_url,
            model,
            temperature,
            MUSIC_SYSTEM,
            (
                "From this shot description, write non_diegetic_music as 1-3 English sentences. "
                "Describe instrumentation, tempo, rhythm, and dynamic change. "
                "No mood words. Output N/A only if the user directions explicitly request no music.\n\n"
                f"Shot description:\n{description}\n\n"
                f"User directions:\n{extra or '(none)'}\n\n"
                "Output only the music paragraph or N/A."
            ),
        )
        return (_format_i2va_output(description, soundscape, music),)

NODE_CLASS_MAPPINGS = {
    "FlaminGalahGrokImageDescriber": FlaminGalahGrokImageDescriber,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahGrokImageDescriber": "Flamin Galah Image Prompt Builder (Grok)",
}
