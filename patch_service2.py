with open('src/mercury/services/campaign_service.py', 'r') as f:
    text = f.read()

broken_str = """            finally:
                try:
                    db_log_queue.put_nowait(None)
                except Exception:
                    pass"""

fixed_str = """            finally:
                try:
                    db_log_queue.put_nowait(None)
                    await writer_task_done.wait()
                except Exception:
                    pass"""

if broken_str in text:
    text = text.replace(broken_str, fixed_str)
    print("Patched!")
else:
    print("NOT FOUND")
    
with open('src/mercury/services/campaign_service.py', 'w') as f:
    f.write(text)

