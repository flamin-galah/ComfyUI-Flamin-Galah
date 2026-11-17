"""Flamin Galah Save MP4 Video

Encode frames (and optional audio) to an H.264 mp4.
Frontend-driven state arrives via the hidden SaveMP4State input.
"""

import os
import uuid
import subprocess
import json
import wave

import folder_paths

try:
    from comfy.cli_args import args as _comfy_cli_args
except Exception:
    _comfy_cli_args = None


LABEL = "Flamin Galah Save MP4 Video"
_CRF = 19
_PIX_FMT = "yuv420p"

DEFAULT_STATE = {
    "folder": "",
    "pattern": "Video_%date:yyyy-MM-dd%_%counter%",
    "format": "mp4",
    "quality": 75,
    "saveOnRun": True,
    "trimToAudio": False,
    "audioFadeMs": 0,
    "counterDigits": 3,
}


def _resolve_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _next_counter(folder, pattern):
    if not os.path.isdir(folder):
        return 1
    import re
    max_n = 0
    for f in os.listdir(folder):
        m = re.search(r"_(\d+)\.mp4$", f)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _write_wav_pcm16(path, waveform, sample_rate):
    import torch
    arr = waveform.detach().cpu().numpy() if hasattr(waveform, "detach") else waveform
    if arr.ndim == 3:
        arr = arr[0]
    channels = arr.shape[0]
    arr = (arr * 32767.0).clip(-32768, 32767).astype("int16")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(arr.T.reshape(-1).tobytes())


class FlaminGalahSaveMP4Video:
    DESCRIPTION = (
        "Flamin Galah Save MP4 Video — encode frames to H.264 mp4 with a live "
        "filename preview, token buttons, folder picker and in-node player."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_frames": ("IMAGE",),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0}),
            },
            "optional": {
                "audio": ("AUDIO",),
                "name": ("STRING", {"forceInput": True}),
            },
            "hidden": {
                "SaveMP4State": "STRING",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "prompt/Flamin Galah"

    def save(self, video_frames, fps, audio=None, name=None,
             SaveMP4State="", prompt=None, extra_pnginfo=None, unique_id=None):

        import numpy as np

        state = dict(DEFAULT_STATE)
        try:
            data = json.loads(SaveMP4State) if SaveMP4State else {}
            if isinstance(data, dict):
                state.update(data)
        except Exception:
            pass

        frames = video_frames
        if frames is None or frames.shape[0] == 0:
            raise ValueError(f"{LABEL}: no frames")

        n_frames, H, W, C = frames.shape
        if C != 3:
            raise ValueError(f"{LABEL}: frames must be RGB")
        if H % 2 or W % 2:
            raise ValueError(f"{LABEL}: width/height must be even ({W}x{H})")

        fps_int = max(1, int(round(float(fps))))
        ffmpeg_path = _resolve_ffmpeg()

        folder_raw = state.get("folder", "").strip()
        if not folder_raw:
            out_dir = folder_paths.get_output_directory()
            file_type = "output"
        else:
            out_dir = os.path.abspath(folder_raw)
            file_type = "external"

        os.makedirs(out_dir, exist_ok=True)

        pattern = state.get("pattern") or DEFAULT_STATE["pattern"]
        digits = max(1, min(8, int(state.get("counterDigits", 3))))
        counter = _next_counter(out_dir, pattern)
        from datetime import datetime
        now = datetime.now()
        resolved = pattern
        resolved = resolved.replace("%date:yyyy-MM-dd%", now.strftime("%Y-%m-%d"))
        resolved = resolved.replace("%date%", now.strftime("%Y-%m-%d"))
        resolved = resolved.replace("%width%", str(W))
        resolved = resolved.replace("%height%", str(H))
        resolved = resolved.replace("%fps%", str(fps_int))
        resolved = resolved.replace("%frames%", str(n_frames))
        resolved = resolved.replace("%duration%", f"{n_frames/fps_int:.1f}".replace(".", "-"))
        if "%counter%" in resolved:
            resolved = resolved.replace("%counter%", f"{counter:0{digits}}")
        if name and "%input%" in resolved:
            resolved = resolved.replace("%input%", str(name).strip())
        if not resolved.endswith(".mp4"):
            resolved += ".mp4"
        resolved = "".join(c if c.isalnum() or c in "._-" else "_" for c in resolved)
        out_path = os.path.join(out_dir, resolved)
        out_filename = os.path.basename(out_path)

        temp_audio = None
        if audio is not None:
            try:
                wf = audio.get("waveform")
                sr = audio.get("sample_rate")
                if wf is not None and getattr(wf, "numel", lambda: 0)() > 0:
                    temp_audio = os.path.join(folder_paths.get_temp_directory(),
                                              f"flamin_{uuid.uuid4().hex}.wav")
                    _write_wav_pcm16(temp_audio, wf, sr)
            except Exception as e:
                print(f"[{LABEL}] audio failed ({e})")
                temp_audio = None

        cmd = [
            ffmpeg_path, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
            "-r", str(fps_int), "-i", "-",
        ]
        if temp_audio:
            cmd += ["-i", temp_audio]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(_CRF), "-pix_fmt", _PIX_FMT]
        if temp_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            if state.get("trimToAudio"):
                cmd += ["-shortest"]
        cmd += [out_path]

        raw = (frames.cpu().numpy() * 255).clip(0, 255).astype(np.uint8).tobytes()
        try:
            proc = subprocess.run(cmd, input=raw, capture_output=True)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
        finally:
            if temp_audio and os.path.exists(temp_audio):
                try:
                    os.remove(temp_audio)
                except OSError:
                    pass

        print(f"[{LABEL}] saved {out_path}")

        entry = {
            "filename": out_filename,
            "subfolder": "",
            "type": file_type,
            "format": "video/mp4",
            "path": out_path,
        }
        return {"ui": {"images": [entry], "flamin_save_mp4": [entry]}}


NODE_CLASS_MAPPINGS = {
    "FlaminGalahSaveMP4Video": FlaminGalahSaveMP4Video,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FlaminGalahSaveMP4Video": "Flamin Galah Save MP4 Video",
}
