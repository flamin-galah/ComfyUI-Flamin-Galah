import subprocess

class FlaminGalahShutdown:
    """Pass-through node that can shut down or reboot the computer (Windows).
    To cancel a pending shutdown or reboot, open a Command Prompt and run: shutdown -a
    """

    DESCRIPTION = (
        "Pass-through shutdown/reboot node (Windows). "
        "To cancel a pending shutdown or reboot, open a Command Prompt and run: shutdown -a"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trigger": ("*",),
                "enabled": ("BOOLEAN", {"default": False}),
                "action": (["shutdown", "reboot"], {"default": "shutdown"}),
                "delay_seconds": ("INT", {"default": 60, "min": 10, "max": 86400, "step": 10}),
            }
        }

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("trigger",)
    FUNCTION = "execute"
    OUTPUT_NODE = True
    CATEGORY = "System"

    def execute(self, trigger, enabled, action, delay_seconds):
        if not enabled:
            return (trigger,)

        try:
            cmd = ["shutdown", "/s" if action == "shutdown" else "/r", "/t", str(delay_seconds)]
            subprocess.run(cmd, check=False)
        except Exception as e:
            print(f"[Flamin Galah] Shutdown error: {e}")

        return (trigger,)

NODE_CLASS_MAPPINGS = {"FlaminGalahShutdown": FlaminGalahShutdown}
NODE_DISPLAY_NAME_MAPPINGS = {"FlaminGalahShutdown": "Flamin Galah Shutdown"}
