import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from config.wsgi import application
from waitress import serve

if __name__ == '__main__':
    print('条款库已启动：http://127.0.0.1:8000', flush=True)
    serve(application, host='127.0.0.1', port=8000, threads=4, max_request_body_size=22*1024*1024)
