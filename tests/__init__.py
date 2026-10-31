import os

if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and os.path.isdir("/opt/pw-browsers"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
