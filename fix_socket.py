with open("tests/test_socketio.py", "r") as f:
    text = f.read()

text = text.replace('def socket_app(mock_user_loader, socketio_instance):', 'def socket_app(app, mock_user_loader, socketio_instance):')
text = text.replace('        app = create_app()\n        app.config["SECRET_KEY"] = "test-key"\n        app.config["TESTING"] = True', '        pass')
# wait, no, the simplest way is to just do:

new_fixture = """@pytest.fixture
def socket_app(app, mock_user_loader, socketio_instance):
    with patch("mercury.web.app.get_app_context") as mock_ctx_getter:
        mock_ctx = Mock()
        mock_ctx.socketio = socketio_instance
        mock_ctx.limiter.limit.side_effect = lambda limit_string: lambda f: f
        mock_ctx_getter.return_value = mock_ctx
        socketio_instance.init_app(app)
        return app
"""

import re
text = re.sub(r'@pytest\.fixture\ndef socket_app.*?return app', new_fixture, text, flags=re.DOTALL)

with open("tests/test_socketio.py", "w") as f:
    f.write(text)
