import re

with open("src/mercury/web/app.py", "r") as f:
    text = f.read()

# We'll inject right before "logger.info("Application initialized successfully")"
# which is around line 354
injection = """
        # --- Start DeadLetterWorker background thread ---
        if not app.config.get("TESTING"):
            _is_reloader = os.environ.get("WERKZEUG_RUN_MAIN")
            if not app.config.get("DEBUG") or _is_reloader == "true":
                def _run_dead_letter_worker(flask_app):
                    import asyncio
                    from ..engine.dead_letter_worker import DeadLetterWorker
                    
                    async def _main():
                        worker = DeadLetterWorker()
                        await worker.start()
                        try:
                            while True:
                                await asyncio.sleep(3600)
                        except asyncio.CancelledError:
                            await worker.stop()
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_main())
                    
                import threading
                dl_thread = threading.Thread(
                    target=_run_dead_letter_worker,
                    args=(app,),
                    daemon=True,
                    name="DeadLetterWorker"
                )
                dl_thread.start()
                logger.info("DeadLetterWorker daemon thread started")

"""

text = text.replace('    logger.info("Application initialized successfully")', injection + '    logger.info("Application initialized successfully")')

with open("src/mercury/web/app.py", "w") as f:
    f.write(text)
