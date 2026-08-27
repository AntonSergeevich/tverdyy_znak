from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("vhod/", views.login_view, name="login"),
    path("vyhod/", views.logout_view, name="logout"),
    path("profil/", views.profile_view, name="profile"),
    # Просмотр кабинета от чужого лица — администратору платформы.
    path("smotret/", views.impersonate_list, name="impersonate_list"),
    path("smotret/<uuid:user_id>/", views.impersonate_start, name="impersonate_start"),
    path("smotret/vernutsya/", views.impersonate_stop, name="impersonate_stop"),
    path("dvuhfaktornaya/", views.two_factor_view, name="two_factor"),
    path("dvuhfaktornaya/nastroyka/", views.two_factor_setup_view, name="two_factor_setup"),
]
