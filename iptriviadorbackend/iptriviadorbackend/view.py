from django.shortcuts import render, login

def login_view(request):
    if request.method == 'POST':
        if login(request, request.POST['username'], request.POST['password']):
            return render(request, 'home.html')
            pass
    return render(request, 'login.html') 