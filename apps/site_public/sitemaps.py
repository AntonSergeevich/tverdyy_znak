from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    protocol = "https"
    changefreq = "weekly"

    def items(self):
        return [
            ("public:landing", 1.0),
            ("public:career", 0.8),
            ("public:thanks", 0.1),
        ]

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]


class LegalSitemap(Sitemap):
    protocol = "https"
    changefreq = "yearly"
    priority = 0.2

    def items(self):
        return ["politika-konfidencialnosti", "soglasie-na-obrabotku-pdn", "polzovatelskoe-soglashenie"]

    def location(self, item):
        return f"/{item}/"


sitemaps = {"static": StaticViewSitemap, "legal": LegalSitemap}
