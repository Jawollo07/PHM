from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render


def auth_view(request):
    return render(request, 'index.html')


def login(request):
    if request.method == 'GET':
        return render(request, 'index.html')
    if request.method != 'POST':
        return HttpResponseNotAllowed(['GET', 'POST'])

    username = request.POST.get('username', '')
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)
    print(f"User {username} tried to log in.")
    print(f"Password: {password}")
    if user is None:
        return render(
            request,
            'index.html',
            {'error': 'Ungültiger Benutzername oder Passwort.'},
            status=400,
        )
    auth_login(request, user)
    return redirect('login_test')
def log_out(request):
    logout(request)
    return redirect('index')

@login_required(login_url='auth')
def site(request):
    return HttpResponse('Successfully logged in!')
