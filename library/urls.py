from django.urls import path
from . import views

urlpatterns = [
    path('categories/', views.categories, name='categories'),
    path('categories/new/', views.category_edit, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/status/', views.category_toggle, name='category_toggle'),
    path('', views.library, name='library'), path('login/', views.sign_in, name='login'),
    path('logout/', views.sign_out, name='logout'), path('password/', views.password, name='password'),
    path('upload/', views.upload, name='upload'), path('documents/<int:pk>/', views.detail, name='detail'),
    path('documents/<int:pk>/preview/', views.preview, name='preview'),
    path('documents/<int:pk>/edit/', views.edit_metadata, name='edit_metadata'),
    path('documents/<int:pk>/download/', views.download, name='download'),
    path('documents/<int:pk>/delete/', views.remove, name='remove'),
    path('trash/', views.trash, name='trash'), path('trash/<int:pk>/restore/', views.restore, name='restore'),
    path('users/', views.users, name='users'), path('users/new/', views.create_user, name='create_user'),
    path('users/<int:pk>/', views.edit_user, name='edit_user'), path('audit/', views.audit_log, name='audit'),
]
