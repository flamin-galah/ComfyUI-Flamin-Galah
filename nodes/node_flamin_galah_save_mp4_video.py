"""Flamin Galah Save MP4 Video

Encode an IMAGE batch (and optional AUDIO) to one H.264 mp4.
save_mode=save writes to ComfyUI's output/ folder;
save_mode=preview writes to ComfyUI's temp/ folder (auto-cleared on restart).

Self-contained: no external helper modules required.
"""

import os
import uuid
import subprocess
import tempfile
import wave
import struct

import folder_paths

try:
    from comfy.cli_args import args as _comfy_cli_args
except Exception:
    _comfy_cli_args = None


LABEL = "Flamin Galah Save MP4 Video"

_CRF = 19
_PIX_FMT = "yuv420p"


def _next_mp4_counter(folder, prefix):
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


def _resolve_ffmpeg():
    """Prefer imageio-ffmpeg, fall back to ffmpeg on PATH."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def _write_wav_pcm16(path, waveform, sample_rate):
    """Write a simple 16-bit PCM WAV from a ComfyUI AUDIO waveform tensor."""
    import torch
    if isinstance(waveform, torch.Tensor):
        arr = waveform.detach().cpu().numpy()
    else:
        arr = waveform
    if arr.ndim == 3:
        arr = arr[0]
    channels, samples = arr.shape
    arr = (arr * 32767.0).clip(-32768, 32767).astype("int16")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        interleaved = arr.T.reshape(-1)
        wf.writeframes(interleaved.tobytes())


class FlaminGalahSaveMP4Video:
    DESCRIPTION = (
        "Flamin Galah Save MP4 Video - encode a batch of frames to a single H.264 mp4 "
        "with an in-node preview. Optional audio is muxed as AAC.\n\n"
        "save_mode=save writes to output/; save_mode=preview writes to temp/ "
        "(cleared on restart)."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_frames": ("IMAGE",),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                "filename_prefix": ("STRING", {"default": "Video"}),
                "save_mode": (["save", "preview"], {"default": "save"}),
                "trim_to_audio": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "audio": ("AUDIO",),
                "audio_fade_ms": ("INT", {"default": 0, "min": 0, "max": 2000, "step": 10}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "prompt/Flamin Galah"

    def save(self, video_frames, fps, filename_prefix="Video",
             save_mode="save", trim_to_audio=False,
             audio_fade_ms=0, audio=None,
             prompt=None, extra_pnginfo=None):

        import numpy as np

        frames = video_frames
        if frames is None or frames.shape[0] == 0:
            raise ValueError(f"{LABEL}: no frames provided")

        n_frames, H, W, C = frames.shape
        if C != 3:
            raise ValueError(f"{LABEL}: frames must be RGB (got {C} channels)")
        if H % 2 or W % 2:
            raise ValueError(f"{LABEL}: width and height must be even for yuv420p (got {W}x{H})")

        fps_int = max(1, int(round(float(fps))))
        ffmpeg_path = _resolve_ffmpeg()

        if save_mode == "preview":
            out_dir = folder_paths.get_temp_directory()
            file_type = "temp"
        else:
            out_dir = folder_paths.get_output_directory()
            file_type = "output"

        full_folder, fname, _, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, out_dir, W, H
        )
        os.makedirs(full_folder, exist_ok=True)
        counter = _next_mp4_counter(full_folder, fname)
        out_filename = f"{fname}_{counter:05d}.mp4"
        out_path = os.path.join(full_folder, out_filename)

        temp_audio_path = None
        if audio is not None:
            try:
                wf = audio.get("waveform")
                sr = audio.get("sample_rate")
                if wf is not None and getattr(wf, "numel", lambda: 0)() > 0:
                    temp_audio_path = os.path.join(
                        folder_paths.get_temp_directory(),
                        f"flamin_save_mp4_{uuid.uuid4().hex}.wav",
                    )
                    _write_wav_pcm16(temp_audio_path, wf, sr)
            except Exception as e:
                print(f"[{LABEL}] audio prep failed ({e}); encoding without audio")
                temp_audio_path = None

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
        if temp_audio_path:
            cmd += ["-i", temp_audio_path]
        cmd += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(_CRF),
            "-pix_fmt", _PIX_FMT,
        ]
        if temp_audio_path:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            if audio_fade_ms and int(audio_fade_ms) > 0:
                fade = int(audio_fade_ms) / 1000.0
                cmd += ["-af", f"afade=t=in:st=0:d={fade}"]
            if trim_to_audio:
                cmd += ["-shortest"]
        cmd += [out_path]

        raw = (frames.cpu().numpy() * 255).clip(0, 255).astype(np.uint8).tobytes()

        try:
            proc = subprocess.run(
                cmd,
                input=raw,
                capture_output=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"{LABEL}: ffmpeg failed:\n{err}")
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass

        print(f"[{LABEL}] saved {out_path}")

        entry = {
            "filename": out_filename,
            "subfolder": subfolder,
            "type": file_type,
            "format": "video/mp4",
        }
        return {"ui": {"images": [entry]}}


NODE_CLASS_MAPPINGS = {
    "FlaminGalahSaveMP4Video": FlaminGalahSaveMP4Video,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahSaveMP4Video": "Flamin Galah Save MP4 Video",
}
