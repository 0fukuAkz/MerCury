import re

with open("src/mercury/web/app.py", "r") as f:
    text = f.read()

# Replace the inner import
text = text.replace("                from .extensions import start_background_loop\n", "")

with open("src/mercury/web/app.py", "w") as f:
    f.write(text)
