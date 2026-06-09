from src.mercury.web.app import create_app
import traceback

app = create_app()
app.config['WTF_CSRF_ENABLED'] = True

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    
    try:
        resp = client.delete('/api/recipients/test.csv')
        print(f'Status: {resp.status_code}')
        print(f'Data: {resp.data}')
    except Exception as e:
        traceback.print_exc()
