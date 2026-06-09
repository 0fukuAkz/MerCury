from src.mercury.web.app import create_app
import os
from src.mercury.utils.app_dirs import get_data_dir

app = create_app()

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    
    # Create file
    d = os.path.join(get_data_dir(), 'recipients')
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, 'book7_3_.csv')
    with open(f, 'w') as out:
        out.write('email\ntest@test.com\n')
        
    print("Deleting book7_3_.csv...")
    resp = client.delete('/api/recipients/book7_3_.csv')
    print("Status:", resp.status_code)
    print("Data:", resp.data.decode())
    print("Exists after?", os.path.exists(f))
