from django.contrib import admin
from django.urls import path
from apps.auth.views import auth_view, login, site
urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', auth_view, name='auth'),
    path('auth/login/', login, name='login'),
    path('auth/login/test/', site, name='login_test'),
]
