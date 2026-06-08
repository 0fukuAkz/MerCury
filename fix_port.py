import os
import re

with open("run.py", "r") as f:
    text = f.read()

# Make it use a port from env or default to 5050 to avoid MacOS Airplay conflicts
text = text.replace('"--bind", "127.0.0.1:5000"', '"--bind", f"127.0.0.1:{os.environ.get(\'PORT\', 5050)}" ')
with open("run.py", "w") as f:
    f.write(text)
print("Updated port in run.py")
