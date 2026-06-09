from src.mercury.web.app import create_app
import traceback
import os
import shutil
from src.mercury.utils.app_dirs import get_data_dir

app = create_app()
app.config['WTF_CSRF_ENABLED'] = True

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    
    try:
        # Create a dummy file
        recipients_dir = os.path.join(get_data_dir(), 'recipients')
        os.makedirs(recipients_dir, exist_ok=True)
        test_file = os.path.join(recipients_dir, 'dummy_test.csv')
        with open(test_file, 'w') as f:
            f.write("email\ntest@example.com\n")
            
        print("File created:", test_file)
        
        # Now delete it
        resp = client.delete('/api/recipients/dummy_test.csv')
        print(f'Status: {resp.status_code}')
        print(f'Data: {resp.data}')
        
        # Check if it was actually deleted
        if os.path.exists(test_file):
            print("File still exists!")
        else:
            print("File successfully deleted!")
            
    except Exception as e:
        traceback.print_exc()
