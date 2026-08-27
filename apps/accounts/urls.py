from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("vhod/", views.login_view, name="login"),
    path("vyhod/", views.logout_view, name="logout"),
    path("profil/", views.profile_view, name="profile"),
    path("dvuhfaktornaya/", views.two_factor_view, name="two_factor"),
    path("dvuhfaktornaya/nastroyka/", views.two_factor_setup_view, name="two_factor_setup"),
]
