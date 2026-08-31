"""
Хранилища файлов.

Всё, что относится к детям, лежит вне MEDIA_ROOT и не отдаётся веб-сервером
напрямую (ТЗ 8.1): такую ссылку нельзя переслать и нельзя подобрать
перебором — она проходит через вью, которая проверяет права.

Хранилище задаётся функцией, а не готовым объектом: Django записывает в
миграцию то, что видит, и абсолютный путь с машины разработчика уехал бы
на сервер вместе с миграцией. Функцию он сохраняет по имени.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    """
    Файлы с персональными данными.

    Путь читается из настроек при каждом обращении, а не один раз при
    сборке модели. Django создаёт хранилище в момент описания поля — то
    есть при импорте, — и запомненный тогда каталог остался бы прежним,
    даже если настройку потом поменяли. На сервере это незаметно, а вот
    тесты писали бы файлы в настоящее хранилище и не убирали за собой.
    """

    @property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def private_storage() -> PrivateMediaStorage:
    return PrivateMediaStorage()
