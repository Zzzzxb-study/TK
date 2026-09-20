from django.urls import include, path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from django.contrib.staticfiles.views import serve

urlpatterns = [path('', include('library.urls'))]
if not settings.PRODUCTION:
    urlpatterns += [path('static/<path:path>', serve, {'insecure': True})]
