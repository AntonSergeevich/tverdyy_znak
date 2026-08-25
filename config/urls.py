from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.accounts.views import healthz
from apps.site_public.sitemaps import sitemaps
from apps.site_public.views import robots_txt

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),
    path("", include("apps.accounts.urls")),
    path("kabinet/", include("apps.journal.urls")),
    path("", include("apps.site_public.urls")),
]

if settings.DEBUG:
    # Панель отладки нужна, чтобы ловить N+1 на списках (ТЗ 9.1).
    urlpatterns.insert(0, path("__debug__/", include("debug_toolbar.urls")))
