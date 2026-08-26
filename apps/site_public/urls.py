from django.urls import path

from apps.site_public import views
from apps.site_public.models import LegalDocument

app_name = "public"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("proforientaciya/", views.career, name="career"),
    path("pedagogi/", views.teachers, name="teachers"),
    path("zayavka/", views.lead_create, name="lead_create"),
    path("spasibo/", views.thanks, name="thanks"),
    path(
        "politika-konfidencialnosti/",
        views.legal, {"kind": LegalDocument.Kind.PRIVACY}, name="legal_privacy",
    ),
    path(
        "soglasie-na-obrabotku-pdn/",
        views.legal, {"kind": LegalDocument.Kind.CONSENT}, name="legal_consent",
    ),
    path(
        "polzovatelskoe-soglashenie/",
        views.legal, {"kind": LegalDocument.Kind.TERMS}, name="legal_terms",
    ),
]
