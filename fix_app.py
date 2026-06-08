with open("src/mercury/web/app.py", "r") as f:
    text = f.read()

import re

# We want to replace everything from "# --- Start DeadLetterWorker" up to "    logger.info("Application initialized successfully")"
start_str = "        # --- Start DeadLetterWorker background thread ---"
end_str = "    logger.info(\"Application initialized successfully\")"

start_idx = text.find(start_str)
end_idx = text.find(end_str)

if start_idx != -1 and end_idx != -1:
    new_code = """        # --- Start DeadLetterWorker on background loop ---
        if not app.config.get("TESTING"):
            _is_reloader = os.environ.get("WERKZEUG_RUN_MAIN")
            if not app.config.get("DEBUG") or _is_reloader == "true":
                from .extensions import start_background_loop
                import asyncio
                from ..engine.dead_letter_worker import DeadLetterWorker
                
                async def _start_worker():
                    worker = DeadLetterWorker()
                    await worker.start()
                    # The bound method process_loop holds reference to worker
                    
                loop = start_background_loop()
                asyncio.run_coroutine_threadsafe(_start_worker(), loop)
                logger.info("DeadLetterWorker scheduled on background loop")

"""
    new_text = text[:start_idx] + new_code + text[end_idx:]
    with open("src/mercury/web/app.py", "w") as f:
        f.write(new_text)
    print("Fixed app.py")
else:
    print("Could not find bounds to replace in app.py")

