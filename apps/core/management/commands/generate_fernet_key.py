from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Сгенерировать ключ шифрования полей с ПДн для FIELD_ENCRYPTION_KEYS"

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write(key)
        self.stdout.write(
            self.style.WARNING(
                "\nПоложите ключ первым в FIELD_ENCRYPTION_KEYS в .env.\n"
                "Старые ключи оставляйте в списке до перешифровки — иначе данные не прочитать.\n"
                "Ключ не должен лежать в репозитории и в том же бэкапе, что и база."
            )
        )
