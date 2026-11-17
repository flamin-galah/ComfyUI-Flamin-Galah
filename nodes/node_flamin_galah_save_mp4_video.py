"""Flamin Galah Save MP4 Video - the quick one.

Encode an IMAGE batch OR a core VIDEO (and optional AUDIO) to one H.264 mp4.
save_mode=save writes to ComfyUI's output/ folder; save_mode=preview writes to
ComfyUI's temp/ folder (auto-cleared on restart).

Deliberately few knobs and opinionated defaults.
"""

import os
import uuid

import folder_paths

from ._video_encode_helpers import (
    audio_fade_args,
    build_video_meta_tags,
    civitai_video_prompt,
    claim_counter_path,
    color_args,
    encode_frames,
    validate_rgb_frames,
    metadata_movflags,
    write_ffmetadata_tags,
    _resolve_ffmpeg,
    _write_wav_pcm16,
)

from ._save_helpers import (
    RUN_TIME_TOKEN,
    _next_counter,
    _safe_prefix,
    fill_run_time,
    note_run_start,
    run_time_text,
)
from ._video_input_helpers import resolve_sources

# Honour ComfyUI's global --disable-metadata flag (same as SaveImage).
try:
    from comfy.cli_args import args as _comfy_cli_args
except Exception:
    _comfy_cli_args = None


LABEL = "Flamin Galah Save MP4 Video"

# Hardcoded encoder defaults — exposed as widgets earlier, removed for a
# cleaner UI. Bring them back to INPUT_TYPES if a workflow needs control.
_CRF = 19
_PIX_FMT = "yuv420p"


def _next_mp4_counter(folder, prefix):
    """Find the next free counter N for `<folder>/<prefix>_<N:05d>.mp4`.

    folder_paths.get_save_image_path's built-in counter assumes Comfy's
    `<prefix>_<N>_.<ext>` pattern (note the trailing underscore) and parses
    `int("00001.mp4")` for our cleaner `<prefix>_<N>.mp4` — which raises and
    silently returns 1, so every save overwrites Video_00001.mp4. We scan
    ourselves instead.
    """
    if not os.path.isdir(folder):
        return 1
    pat = prefix + "_"
    max_n = 0
    for f in os.listdir(folder):
        if not f.startswith(pat) or not f.endswith(".mp4"):
            continue
        middle = f[len(pat):-len(".mp4")]
        try:
            n = int(middle)
        except ValueError:
            continue
        if n > max_n:
            max_n = n
    return max_n + 1


class FlaminGalahSaveMP4Video:
    """Encode an IMAGE batch OR a core VIDEO (and optional AUDIO) to one H.264 mp4.

    save_mode=save writes to ComfyUI's output/ folder; save_mode=preview
    writes to ComfyUI's temp/ folder (auto-cleared on restart) so users can
    iterate without cluttering output/. Deliberately few knobs and opinionated
    defaults; Save Video Pixaroma is the one with folders and naming.
    """

    DESCRIPTION = (
        "Flamin Galah Save MP4 Video - encode a batch of frames, or a whole video, to a "
        "single H.264 mp4 with a built-in <video> preview right on the node "
        "body so you can watch the result without leaving ComfyUI. Once it has "
        "made a video, its size and length are shown on the top right of the "
        "node.\n\n"
        "There are two inputs because ComfyUI has two different kinds of video "
        "on the wire, and you only ever need one of them. Use video_frames for "
        "a batch of frames, such as the video_frames output of Load Video "
        "Pixaroma or the frames straight out of a video model. Use video for "
        "ComfyUI's own video type, such as the output of its Load Video node; "
        "the sound stored in that video comes along with it. If both are "
        "connected, video_frames is the one that is used and the node says so "
        "in the console.\n\n"
        "A video wired into the video input keeps its own frame rate, so it "
        "comes out the same length it went in and its sound stays in step; the "
        "fps setting applies to video_frames only. It is decoded and encoded "
        "again, so re-saving one costs a little quality, and a long clip is "
        "held in memory while it is read. Feeding frames avoids both.\n\n"
        "Frames stream straight to ffmpeg's stdin (no temp PNG files); audio "
        "is muxed in as AAC 192k. Pairs with AudioReact Pixaroma but works "
        "with any source that produces frames + AUDIO.\n\n"
        "The whole workflow is saved inside the mp4, so you can drag the video "
        "back onto the canvas later and get the graph back, exactly like dragging "
        "a PNG. It is stored the same way ComfyUI's own video saving stores it, "
        "so ComfyUI reads it back on its own.\n\n"
        "Turn on 'Add Civitai generation info' in the node's settings (right-click "
        "the node) and Civitai shows the prompt, steps, CFG, seed, sampler and "
        "model name of the videos you upload; your workflow stays in the video as "
        "before.\n\n"
        "ffmpeg binary is auto-located: imageio-ffmpeg's bundled exe is "
        "preferred (no system install needed - 'pip install imageio-ffmpeg'), "
        "with ffmpeg on PATH as a fallback. yuv420p requires even width and "
        "height; the node surfaces a clear error rather than ffmpeg's opaque "
        "crash if dimensions are odd.\n\n"
        "Encoder is hardcoded to libx264 / preset medium / CRF 19. Bring those "
        "back to INPUT_TYPES if a workflow needs per-clip control."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0,
                    "tooltip": "Output frame rate for the video_frames input. Wire Audio React Pixaroma's fps output here so it always matches what produced the frames. A video wired into the video input brings its own frame rate and keeps it, so this is ignored for that input."
                }),
                "filename_prefix": ("STRING", {
                    "default": "Video",
                    "tooltip": "Filename stem. The node appends a 5-digit counter and .mp4 (e.g. Video_00001.mp4). Use '/' for subfolders, date tokens like %date:yyyy-MM-dd%, %run_time% for how long the run took until this node saved (e.g. 1m05s), and node references like %Seed Pixaroma.seed% that print another node's field value into the name."
                }),
                "save_mode": (["save", "preview"], {
                    "default": "save",
                    "tooltip": "save: write to ComfyUI's output/ folder, kept across restarts. preview: write to ComfyUI's temp/ folder, auto-cleared on restart, so use it while iterating and you will not clutter output/. The in-node video preview works the same in both modes."
                }),
                "trim_to_audio": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Off (default): keep every video frame; the audio simply ends where it ends. On: end the video exactly at the audio's length (ffmpeg -shortest), for when the audio is the master (e.g. with Audio React). On can drop the last frame or two when the audio is slightly shorter than the video."
                }),
            },
            "optional": {
                "video_frames": ("IMAGE", {
                    "tooltip": "Frame batch to encode. Wire Audio React Pixaroma's video_frames output here. Use this or video, whichever kind you have; if both are wired this one is used."
                }),
                "audio": ("AUDIO", {
                    "tooltip": "Optional audio track to mux into the mp4 as AAC 192k. Connect Audio React Pixaroma's audio output here. A video wired into the video input brings its own sound, which this input overrides."
                }),
                "audio_fade_ms": ("INT", {
                    "default": 0, "min": 0, "max": 2000, "step": 10,
                    "tooltip": "Fade the sound in over this many milliseconds at the very start. 0 is off. AI video models often start their audio at full level in a single step, which is heard as a click; about 120 helps a lot and is too short to notice as a fade. Leave it at 0 when you are just re-saving a video whose sound you do not want altered."
                }),
                "video": ("VIDEO", {
                    "tooltip": "A video straight from ComfyUI's own video type, such as its Load Video node, instead of a batch of frames. Its sound comes along with it. Wire this or video_frames, never both."
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
                "CivitaiMeta": "STRING",
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "👑 Pixaroma/🖼️ Image"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        note_run_start()
        return False

    def save(self, video_frames=None, fps=24.0, filename_prefix="Video",
             save_mode="save", trim_to_audio=False,
             audio_fade_ms=0, audio=None, video=None,
             prompt=None, extra_pnginfo=None, unique_id=None, CivitaiMeta=""):
        run_time = run_time_text()
        crf = self._CRF
        pix_fmt = self._PIX_FMT
        fps_int = max(1, int(round(float(fps))))

        frames, video_audio, video_fps, source_note = resolve_sources(
            video_frames, video, LABEL,
        )
        if source_note:
            print(source_note)
        if video_fps is not None:
            if abs(float(video_fps) - float(fps)) > 0.001:
                print(f"[Pixaroma] {LABEL} - using the video's own {float(video_fps):g} fps "
                      f"instead of the fps widget's {float(fps):g}, so it keeps its "
                      "timing.")
            fps_int = max(1, int(round(float(video_fps))))
        if audio is None and video_audio is not None:
            audio = video_audio

        n_frames, H, W = validate_rgb_frames(frames, LABEL, pix_fmt)

        ffmpeg_path = _resolve_ffmpeg(LABEL)

        if save_mode == "preview":
            out_dir = folder_paths.get_temp_directory()
            file_type = "temp"
        else:
            out_dir = folder_paths.get_output_directory()
            file_type = "output"

        filename_prefix = _safe_prefix(filename_prefix) or "Video"
        if RUN_TIME_TOKEN in filename_prefix:
            head, sep, leaf = filename_prefix.rpartition("/")
            filename_prefix = fill_run_time(head, run_time) + sep + leaf
        full_folder, fname, _ignored, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, out_dir, W, H,
        )
        os.makedirs(full_folder, exist_ok=True)
        if RUN_TIME_TOKEN in fname:
            scan = lambda: _next_counter(full_folder, fname + "_%counter%.mp4")  # noqa: E731
        else:
            scan = lambda: _next_mp4_counter(full_folder, fname)  # noqa: E731
        out_path, out_filename, counter = claim_counter_path(
            full_folder,
            lambda n: fill_run_time(f"{fname}_{n:05d}.mp4", run_time),
            start=scan,
            label=LABEL,
        )

        temp_audio_path = None
        try:
            if audio is not None and audio.get("waveform") is not None \
                    and audio["waveform"].numel() > 0:
                temp_audio_path = os.path.join(
                    folder_paths.get_temp_directory(),
                    f"pixaroma_save_mp4_{uuid.uuid4().hex}.wav",
                )
                os.makedirs(os.path.dirname(temp_audio_path), exist_ok=True)
                _write_wav_pcm16(temp_audio_path, audio["waveform"], audio["sample_rate"])
        except Exception as e:
            print(f"[Pixaroma] {LABEL} — could not prepare audio ({e}); "
                  f"encoding without it.")
            if temp_audio_path is not None and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass
            temp_audio_path = None

        metadata_path = None
        disable_meta = bool(getattr(_comfy_cli_args, "disable_metadata", False))
        if not disable_meta:
            meta_tags = build_video_meta_tags(
                prompt, extra_pnginfo,
                civitai_prompt=civitai_video_prompt(
                    CivitaiMeta, prompt, unique_id, W, H, LABEL))
            if meta_tags:
                try:
                    metadata_path = os.path.join(
                        folder_paths.get_temp_directory(),
                        f"pixaroma_save_mp4_meta_{uuid.uuid4().hex}.txt",
                    )
                    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
                    write_ffmetadata_tags(metadata_path, meta_tags)
                except Exception as e:
                    print(f"[Pixaroma] {LABEL} — could not prepare metadata ({e}); "
                          f"saving without it.")
                    if metadata_path is not None and os.path.exists(metadata_path):
                        try:
                            os.remove(metadata_path)
                        except OSError:
                            pass
                    metadata_path = None

        cmd = [
            ffmpeg_path, "-y",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}",
            "-r", str(fps_int),
            "-i", "-",
        ]
        if temp_audio_path is not None:
            cmd += ["-i", temp_audio_path]
        meta_input_index = None
        if metadata_path is not None:
            meta_input_index = 1 + (1 if temp_audio_path is not None else 0)
            cmd += ["-i", metadata_path]
        cmd += color_args()
        cmd += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(crf),
            "-pix_fmt", pix_fmt,
        ]
        if temp_audio_path is not None:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            cmd += audio_fade_args(audio_fade_ms)
            if trim_to_audio:
                cmd += ["-shortest"]
        if meta_input_index is not None:
            cmd += ["-map_metadata", str(meta_input_index)]
            cmd += metadata_movflags()
        cmd += [out_path]

        print(f"[Pixaroma] {LABEL} [{save_mode}] — writing {n_frames} frames @ {fps_int}fps "
              f"({W}x{H}, crf={crf}, {pix_fmt}"
              f"{', +audio' if temp_audio_path else ''}) -> {out_filename}")

        broke_pipe = encode_frames(
            cmd, frames, out_path,
            temp_paths=[temp_audio_path, metadata_path],
            label=LABEL,
        )

        if broke_pipe:
            print(f"[Pixaroma] {LABEL} — video trimmed to the audio length (trim_to_audio is on).")
        if save_mode == "preview":
            print(f"[Pixaroma] {LABEL} — preview written to temp/ (auto-cleared on restart): {out_path}")
        else:
            print(f"[Pixaroma] {LABEL} — saved {out_path}")

        entry = {
            "filename": out_filename,
            "subfolder": subfolder,
            "type": file_type,
            "format": "video/mp4",
        }
        return {"ui": {"images": [entry], "pixaroma_videos": [entry]}}


NODE_CLASS_MAPPINGS = {
    "FlaminGalahSaveMP4Video": FlaminGalahSaveMP4Video,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahSaveMP4Video": "Flamin Galah Save MP4 Video",
}
