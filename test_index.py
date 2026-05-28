import email.message
import traceback

def extract_sender(message):
    from_header = message.get("From")
    if not from_header:
        return ""
    import email.utils
    parsed = email.utils.getaddresses([from_header])
    return parsed[0][1]

msg = email.message.EmailMessage()
try:
    print(extract_sender(msg))
except Exception as e:
    print("msg:", type(e), str(e))

msg['From'] = ""
try:
    print(extract_sender(msg))
except Exception as e:
    print("msg_empty:", type(e), str(e))
