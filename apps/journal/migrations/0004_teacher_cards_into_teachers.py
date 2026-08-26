"""
Публичные карточки педагогов переезжают в самих педагогов.

Раньше человек заводился дважды: как Teacher в журнале и как TeacherCard
на сайте. Два источника правды об одном человеке однажды расходятся —
на сайте один предмет, в журнале другой. После переноса педагог один,
а поля публикации живут на нём.

Карточкам без учётной записи заводится пользователь без пароля и
неактивный: человек на сайте есть, доступа в кабинет у него нет. Выдать
доступ администратор может отдельной кнопкой — это осознанное действие,
а не побочный эффект миграции.
"""
from django.db import migrations


def transliterate(text):
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    out = []
    for char in (text or "").lower():
        if char in table:
            out.append(table[char])
        elif char.isascii() and (char.isalpha() or char.isdigit()):
            out.append(char)
    return "".join(out) or "teacher"


def move_cards(apps, schema_editor):
    TeacherCard = apps.get_model("site_public", "TeacherCard")
    Teacher = apps.get_model("journal", "Teacher")
    User = apps.get_model("accounts", "User")
    Membership = apps.get_model("accounts", "Membership")

    for card in TeacherCard.objects.all():
        parts = card.full_name.split()
        last_name = parts[0] if parts else card.full_name
        first_name = parts[1] if len(parts) > 1 else ""
        middle_name = parts[2] if len(parts) > 2 else ""

        teacher = (
            Teacher.objects.filter(
                organization_id=card.organization_id,
                user__last_name__iexact=last_name,
                user__first_name__iexact=first_name,
            ).first()
            if first_name
            else None
        )

        if teacher is None:
            login = transliterate(last_name)
            suffix = 1
            candidate = login
            while User.objects.filter(username=candidate).exists():
                suffix += 1
                candidate = f"{login}{suffix}"
            user = User.objects.create(
                username=candidate,
                last_name=last_name,
                first_name=first_name,
                middle_name=middle_name,
                # Доступа нет, пока администратор не выдаст его явно.
                password="!",
                is_active=False,
            )
            Membership.objects.create(
                user=user, organization_id=card.organization_id, role="teacher"
            )
            teacher = Teacher.objects.create(
                organization_id=card.organization_id, user=user, hourly_rate=0
            )

        teacher.photo = card.photo
        teacher.subject_line = card.subject_line
        teacher.experience = card.experience
        teacher.bio = card.bio
        teacher.public_position = card.position
        teacher.is_published = card.is_published
        teacher.is_featured = card.is_featured
        teacher.save()


def back(apps, schema_editor):
    """Обратный перенос не нужен: карточки остаются на месте до удаления модели."""


class Migration(migrations.Migration):
    dependencies = [
        ("journal", "0003_teacher_bio_teacher_experience_teacher_is_featured_and_more"),
        ("site_public", "0003_teacherreview"),
        ("accounts", "0003_user_username_user_user_username_unique_not_blank"),
    ]

    operations = [migrations.RunPython(move_cards, back)]
