with open("run.py", "r") as f:
    text = f.read()

# See if dotenv is already used
if "dotenv" not in text:
    import re
    # We want to put it right at the top of the main logic or after imports
    text = text.replace("import threading\nfrom pathlib import Path\n", "import threading\nfrom pathlib import Path\n\ntry:\n    from dotenv import load_dotenv\n    load_dotenv()\nexcept ImportError:\n    pass\n")
    with open("run.py", "w") as f:
        f.write(text)
    print("Fixed run.py to load .env")
