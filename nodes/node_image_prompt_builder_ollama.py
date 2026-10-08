"""
ComfyUI custom node: Flamin Galah Image Prompt Builder (Ollama)
Uses local Ollama only. A vision model describes the image;
a second local Ollama model writes either an H3 I2V prompt or a I2I paragraph.
"""

import json
import urllib.request
import urllib.error
import base64
import io
import re

try:
    import torch
    import numpy as np
    from PIL import Image
except ImportError:
    torch = None
    np = None
    Image = None


I2V_FIRST_FRAME_LINE = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)

SINGLE_IMAGE_RULES = """There is exactly one supplied source image; only the first image in the input batch is used.
Do not invent or refer to additional reference images, comparison images, or an end-frame image.
Describe all action as a continuation of that one image, not a transition to another picture.
Use "the source image" if a reference is needed in prose; do not write numbered Picture or Image labels.
The formatter alone adds the required first-frame reference marker for video output.
Preserve quoted text actually visible in the image verbatim."""

OLLAMA_VISION_SYSTEM = """You are a precise visual describer for image-to-video generation.
Describe the supplied image in rich, objective detail suitable as a first-frame anchor.
Include: overall style, lighting, composition, camera angle, subject appearance (body, face, hair, expression), clothing or lack of clothing, pose, body language, environment, key objects, textures (skin, fabric, etc.), and atmosphere.
Be explicit and specific. Do not invent a different person, outfit, or setting. Do not add sound. Output only the description paragraph, nothing else.
""" + SINGLE_IMAGE_RULES


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


# Numbered labels can leak out of either model even with single-image instructions.
# Keep literal visible text in double quotes untouched, and leave the official
# video header to the formatter rather than rewriting it as scene prose.
_QUOTED_TEXT_RE = re.compile(r'("(?:\\.|[^"\\])*"|“[^”]*”)')
_IMAGE_LABEL = (
    r"(?:reference[ \t]+)?(?:picture|image)[ \t]*#?[ \t]*"
    r"(?:[0-9]+|one|two|three|four|five|six|seven|eight|nine|ten)(?!\w)"
)
_NUMBERED_IMAGE_REFERENCE_RE = re.compile(
    r"(?<!\w)(?:(?:the|this|that|an?)[ \t]+)?(?:"
    r"<[ \t]*" + _IMAGE_LABEL + r"[ \t]*>|"
    r"\[[ \t]*" + _IMAGE_LABEL + r"[ \t]*\]|" + _IMAGE_LABEL + r")",
    re.IGNORECASE,
)


def _normalize_single_image_references(text):
    """Remove invented image numbering from prose, preserving quoted visible text."""
    parts = _QUOTED_TEXT_RE.split(text or "")
    for index in range(0, len(parts), 2):
        parts[index] = _NUMBERED_IMAGE_REFERENCE_RE.sub("the source image", parts[index])
    return "".join(parts)


PROMPT_WRITER_SYSTEM = """You write MiniMax H3 shot descriptions from a source image description.
Keep identity, clothing, body, setting, lighting, and composition from the source description.
If the user provided an enhancement prompt, incorporate every request as action, camera movement, and continuation after the first frame.
If there is no enhancement prompt, keep the first-frame state and add only a natural slight continuation.
Write one continuous paragraph. No lists, no field labels, no sound, no preamble.
""" + SINGLE_IMAGE_RULES


I2V_PROMPT_WRITER_SYSTEM = """You write MiniMax H3 first-frame image-to-video shot descriptions.
Write one continuous English paragraph beginning with [Shot 1]. Derive the visual style from the source image description; do not turn a 2D illustration, animation, logo, or other stylized image into live-action or photorealism.
First anchor the opening at 0.00 seconds to the one supplied source image: establish the source style, camera angle, composition, subject identity, appearance, clothing, colors, pose, lighting, setting, key objects, and spatial relationships.
Then develop forward: first-frame anchor -> action onset -> continuous development -> result or reaction. The user enhancement specifies what happens after the unchanged first frame, not a replacement opening state.
Preserve the source details at frame 0 even when later requested motion changes pose, viewpoint, or framing. Describe camera movement naturally, including amplitude and speed when meaningful.
If no enhancement is supplied, retain the image's opening state and add only a slight, plausible continuation. Do not invent a different person, outfit, setting, or visual style.
Keep any visible text verbatim in English double quotes.
If the user supplies spoken lines or lyrics, include them in this paragraph. Do not invent dialogue or singing. On the first vocalization assign a stable speaker id such as (S1). Put identity, delivery, and the id outside the tag. Inside the tag put only the language label and the verbatim line, for example: The woman with a low voice (S1) says: <d>[English] exact user line.</d>
Diegetic music the characters can hear also belongs in this paragraph. Do not write the overall_soundscape or non_diegetic_music fields.
No lists, field labels, or preamble. Do not write the image-alignment instruction; the formatter adds it separately.
""" + SINGLE_IMAGE_RULES


SOUNDSCAPE_SYSTEM = """You write the H3 overall_soundscape field from a shot description.
Write 1–4 English sentences in one continuous paragraph covering only:
ambient sound; physical action sounds implied by the shot; non-verbal human sounds such as breathing, laughter, or panting.
Do not include dialogue, singing, diegetic music, or non-diegetic music.
Do not use field labels or bullet lists.
Use N/A only when the user explicitly requests complete silence throughout the video. A still or quiet scene alone is not a request for silence. Otherwise describe restrained ambient or physical sounds consistent with the setting and action; do not invent unrelated sound sources.
""" + SINGLE_IMAGE_RULES


MUSIC_SYSTEM = """You write the H3 non_diegetic_music field.
Write 1-3 English sentences describing background music the characters cannot hear. Cover instrumentation, tempo, rhythm, and dynamic change. Do not use abstract mood words or explain the emotional purpose of the score.
If the user names a score, follow that. If the user explicitly requests no music, output N/A. Otherwise write a concrete score that fits the shot's pace and setting.
Do not repeat dialogue, singing, or diegetic music. No field label, no bullet list.
"""


def _strip_i2v_header(description):
    """Remove an exact model-written copy of the official or previous header."""
    vision = (description or "").strip()
    legacy_header = I2V_FIRST_FRAME_LINE.replace("<Picture 1> ", "")
    lines = vision.splitlines()
    if lines and lines[0].strip() in (I2V_FIRST_FRAME_LINE, legacy_header):
        vision = "\n".join(lines[1:]).strip()
    return vision


def _format_i2v_output(description, soundscape="", music=""):
    """H3 image-to-video block: first-frame reference line and three fields."""
    vision = _normalize_single_image_references(_strip_i2v_header(description))
    if not vision:
        raise RuntimeError("Ollama returned no first-frame shot description.")
    if vision.lower().startswith("[shot 1]"):
        body = "[Shot 1]" + vision[len("[Shot 1]"):]
    else:
        body = f"[Shot 1] {vision}"
    sound = _normalize_single_image_references((soundscape or "").strip())
    if not sound:
        raise RuntimeError("Ollama returned no soundscape. Use N/A only for explicitly requested complete silence.")
    score = (music or "").strip() or "N/A"
    return (
        f"{I2V_FIRST_FRAME_LINE}\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        f"non_diegetic_music: {score}"
    )


def _format_i2i_output(description):
    """Plain text paragraph, no H3 field labels."""
    return _normalize_single_image_references(
        _strip_redundant_style_prefix((description or "").strip())
    )



TEXT_TO_VIDEO_SYSTEM = """You write a MiniMax H3 text-to-video shot description from the user's scene directions.
No reference image is supplied. Build the scene from the user's text; do not refer to an uploaded image, a first-frame reference, or <Picture 1>.
Write one continuous English paragraph beginning with [Shot 1]. Establish the requested visual style, subject appearance, composition, setting, and lighting before developing the action, camera motion, and result or reaction.
Follow all supplied scene directions. Preserve the requested style, including animation or illustration; if no style is specified, choose a suitable cinematic style.
If the user supplies spoken lines or lyrics, include them. Do not invent dialogue. Use (S1) and <d>[English] verbatim line.</d>.
Output only the shot paragraph. No field labels, alignment instruction, lists, soundscape, music, or preamble."""


REF2VA_SYSTEM = """You write a MiniMax H3 full-reference (Ref2VA) prompt from two reference images.
The images are character or subject references, not first and last frames.
Picture 1, the first attached image, is the source of <Subject 1>, the primary subject.
Picture 2, the second attached image, is the source of <Subject 2>, the secondary subject.
Do not create standalone <Picture N> lines. Cite each image only inside its subject definition.
Output exactly these six sections, in this order, with these headers and no other preamble:

subject_definitions:
<Subject 1> is the primary subject shown in Picture 1, with the visible identity, face, hair, body, clothing, and distinctive features.
<Subject 2> is the secondary subject shown in Picture 2, with the visible identity, face, hair, body, clothing, and distinctive features.

summary:
[reference generation] One English paragraph describing the target video and how <Subject 1> and <Subject 2> are used.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - identity, facial features, clothing, and visual characteristics from Picture 1 are retained.
<Subject 2> (appears in [Shot 1]): fully_preserved - identity, facial features, clothing, and visual characteristics from Picture 2 are retained.

detailed_description:
One detailed English playback description. Begin with the visual style. Then write [Shot 1]. On first appearance, restate each subject's referenced appearance, position, and action. Include user-supplied dialogue only, using (S1) and (S2) and <d>[English] verbatim line.</d>. Do not invent dialogue.

overall_soundscape:
1-4 English sentences of ambient sound, physical action sounds, and non-verbal human sounds. No dialogue or music. Use N/A only if the user explicitly requests complete silence.

non_diegetic_music:
1-3 English sentences of audience-only score, covering instrumentation, tempo, rhythm, and dynamics. Use N/A only if the user requests no music.

Preserve both identities. Do not merge the two people into one. Write in English except for verbatim dialogue and visible text.
"""


_REF2VA_HEADERS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


def _present_image(image):
    if image is None:
        return None
    if getattr(image, "shape", (1,))[0] == 0:
        return None
    return image


def _format_ref2va_output(raw):
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty reference-to-video prompt.")
    lowered = text.lower()
    positions = []
    for header in _REF2VA_HEADERS:
        index = lowered.find(header + ":")
        if index < 0:
            raise RuntimeError(f"Ollama reference prompt is missing {header}:")
        positions.append((index, header))
    positions.sort()
    chunks = {}
    for pos, (index, header) in enumerate(positions):
        start = index + len(header) + 1
        end = positions[pos + 1][0] if pos + 1 < len(positions) else len(text)
        chunks[header] = text[start:end].strip()
    missing = [header for header in _REF2VA_HEADERS if not chunks.get(header)]
    if missing:
        raise RuntimeError("Ollama reference prompt has empty sections: " + ", ".join(missing))
    return "\n\n".join(f"{header}:\n{chunks[header]}" for header in _REF2VA_HEADERS)


class FlaminGalahImageDescriber:

    @classmethod
    def INPUT_TYPES(cls):
        model_list = _get_ollama_models()

        return {
            "required": {
                "output_mode": (["Image to Video", "Image to Image"], {
                    "default": "Image to Video"
                }),
                "extra_description": ("STRING", {
                    "default": "",
                    "multiline": True
                }),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
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
        "Flamin Galah Image Prompt Builder (Ollama) – "
        "local Ollama only. Runs with image_1, image_2, both, or none. "
        "One image writes I2V or I2I. Both images write Ref2VA, or a two-subject I2I paragraph. "
        "No image writes T2VA, or a plain paragraph, from extra_description."
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
        output_mode="Image to Video",
        extra_description="",
        image_1=None,
        image_2=None,
        ollama_url="http://localhost:11434",
        vision_model="",
        prompt_model="",
        enhance_model="",
        temperature=0.2,
        lora_tag="",
    ):
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
        mode = "I2I" if raw in ("i2i", "image to image", "t2i", "t2t") else "I2V"
        extra = (extra_description or "").strip()
        extra_block = extra if extra else "(none)"
        primary = _present_image(image_1)
        secondary = _present_image(image_2)

        if primary is None and secondary is None:
            if not extra:
                raise RuntimeError(
                    "Connect image_1, image_2, or both, or enter scene directions in extra_description."
                )
            output = self._generate_text_only(
                mode, extra, extra_block, ollama_url, prompt_model, temperature
            )
            return (self._append_lora(output, lora_tag),)
        if primary is not None and secondary is not None:
            output = self._generate_two_images(
                mode, primary, secondary, extra, extra_block, ollama_url, vision_model, prompt_model, temperature
            )
            return (self._append_lora(output, lora_tag),)

        image = primary if primary is not None else secondary
        frames_b64 = [_tensor_to_base64_png(image)]

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
        source_description = _normalize_single_image_references(source_description)

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
                "Begin [Shot 1] with the actual style and opening composition of the one supplied source image. "
                "Preserve the source identity, clothing, colors, pose, lighting, setting, "
                "key objects, and spatial relationships at 0.00 seconds. "
                "Then describe action onset, continuous development, and the result or reaction. "
                "Apply requested action and camera changes only after the first frame. "
                "Output only the rewritten paragraph."
            )

        description = self._call_ollama(
            rewrite_prompt,
            ollama_url,
            prompt_model,
            temperature,
            PROMPT_WRITER_SYSTEM if mode == "I2I" else I2V_PROMPT_WRITER_SYSTEM,
        )
        if mode == "I2V":
            description = _strip_i2v_header(description)
        description = _normalize_single_image_references(description)

        if mode == "I2I":
            output = _format_i2i_output(description)
        else:
            soundscape = self._call_ollama(
                (
                    "From this shot description, write overall_soundscape as 1–4 English sentences "
                    "in one paragraph. Include only ambient sound, physical action sounds implied "
                    "by the shot, and non-verbal human sounds. No dialogue, singing, or music.\n\n"
                    f"Shot description:\n{description}\n\n"
                    f"User directions:\n{extra_block}\n\n"
                    "Use N/A only if these user directions explicitly request complete silence "
                    "throughout the video; a static or quiet image alone does not imply silence. "
                    "Output only the paragraph."
                ),
                ollama_url,
                prompt_model,
                temperature,
                SOUNDSCAPE_SYSTEM,
            )
            music = self._call_ollama(
                (
                    "From this shot description, write non_diegetic_music as 1-3 English sentences. "
                    "Describe instrumentation, tempo, rhythm, and dynamic change. "
                    "No mood words. Output N/A only if the user directions explicitly request no music.\n\n"
                    f"Shot description:\n{description}\n\n"
                    f"User directions:\n{extra_block}\n\n"
                    "Output only the music paragraph or N/A."
                ),
                ollama_url,
                prompt_model,
                temperature,
                MUSIC_SYSTEM,
            )
            output = _format_i2v_output(description, soundscape, music)

        return (self._append_lora(output, lora_tag),)

    def _append_lora(self, output, lora_tag):
        lora = (lora_tag or "").strip()
        if lora:
            return f"{output}\n\nLoRA tag: {lora}"
        return output

    def _generate_text_only(self, mode, extra, extra_block, ollama_url, prompt_model, temperature):
        if mode == "I2I":
            return self._call_ollama(
                (
                    "Write a single image-prompt paragraph from these directions. "
                    "No reference image is supplied. Do not mention an uploaded image.\n\n"
                    f"Directions:\n{extra}\n\n"
                    "Output only the paragraph."
                ),
                ollama_url,
                prompt_model,
                temperature,
                "You write a plain image prompt paragraph. No field labels or preamble.",
            )
        description = self._call_ollama(
            (
                "Write one H3 text-to-video shot paragraph from these scene directions. "
                "No image is supplied.\n\n"
                f"Scene directions:\n{extra}\n\n"
                "Output only the shot paragraph."
            ),
            ollama_url,
            prompt_model,
            temperature,
            TEXT_TO_VIDEO_SYSTEM,
        )
        soundscape = self._call_ollama(
            (
                "From this shot description, write overall_soundscape as 1-4 English sentences. "
                "No dialogue, singing, or music. Use N/A only for explicitly requested complete silence.\n\n"
                f"Shot description:\n{description}\n\nUser directions:\n{extra_block}\n\n"
                "Output only the paragraph."
            ),
            ollama_url,
            prompt_model,
            temperature,
            SOUNDSCAPE_SYSTEM,
        )
        music = self._call_ollama(
            (
                "From this shot description, write non_diegetic_music as 1-3 English sentences. "
                "Output N/A only if the user requests no music.\n\n"
                f"Shot description:\n{description}\n\nUser directions:\n{extra_block}\n\n"
                "Output only the music paragraph or N/A."
            ),
            ollama_url,
            prompt_model,
            temperature,
            MUSIC_SYSTEM,
        )
        body = description.strip()
        if not body.lower().startswith("[shot 1]"):
            body = f"[Shot 1] {body}"
        return (
            f"integrated_multimodal_description: {body}\n\n"
            f"overall_soundscape: {soundscape.strip()}\n\n"
            f"non_diegetic_music: {music.strip() or 'N/A'}"
        )

    def _generate_two_images(self, mode, primary, secondary, extra, extra_block, ollama_url, vision_model, prompt_model, temperature):
        frames = [_tensor_to_base64_png(primary), _tensor_to_base64_png(secondary)]
        if mode == "I2I":
            return self._call_ollama(
                (
                    "The first image is the primary subject and the second is the secondary subject. "
                    "Write one image-prompt paragraph that keeps both identities, clothing, and visual traits. "
                    "Do not merge them into one person.\n\n"
                    f"User directions:\n{extra_block}\n\n"
                    "Output only the paragraph."
                ),
                ollama_url,
                vision_model,
                temperature,
                "You write a plain two-subject image prompt. No field labels or preamble.",
                images_b64=frames,
            )
        raw = self._call_ollama(
            (
                "The first image is Picture 1, the primary subject reference. "
                "The second image is Picture 2, the secondary subject reference. "
                "Write the six-section H3 Ref2VA prompt. Do not use standalone Picture lines.\n\n"
                f"User directions:\n{extra_block}\n\n"
                "Output only the six sections."
            ),
            ollama_url,
            vision_model,
            temperature,
            REF2VA_SYSTEM,
            images_b64=frames,
        )
        return _format_ref2va_output(raw)


NODE_CLASS_MAPPINGS = {
    "FlaminGalahImageDescriber": FlaminGalahImageDescriber,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahImageDescriber": "Flamin Galah Image Prompt Builder (Ollama)",
}
