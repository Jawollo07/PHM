from django.contrib import admin
from django.urls import path
from apps.auth.views import auth_view, login, site, log_out
from apps.customers.views import account_view

urlpatterns = [
    # path('', index, name='index'), # type: ignore
    path('admin/', admin.site.urls),
    path('auth/', auth_view, name='auth'),
    path('auth/login/', login, name='login'),
    path('auth/logout/', log_out, name='logout'),
    path('auth/login/test/', site, name='login_test'),
    path('account/', account_view, name='account'),

]
