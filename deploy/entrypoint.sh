#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec waitress-serve --listen=0.0.0.0:8000 --threads=8 --trusted-proxy="*" --trusted-proxy-count=1 --trusted-proxy-headers="x-forwarded-for x-forwarded-proto" --max-request-body-size=23068672 config.wsgi:application
