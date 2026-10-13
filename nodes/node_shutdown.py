import subprocess

class ShutdownComputer:
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

NODE_CLASS_MAPPINGS = {"ShutdownComputer": ShutdownComputer}
NODE_DISPLAY_NAME_MAPPINGS = {"ShutdownComputer": "Flamin Galah Shutdown"}
