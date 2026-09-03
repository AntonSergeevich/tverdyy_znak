"""
У домашнего задания появляется жизненный цикл.

До этой миграции строка HomeworkMark значила ровно одно: «ученик нажал
„сделал“». Момент нажатия отдельно не хранился — его заменяло created_at.
Теперь отметка ученика и проверка педагога разведены, поэтому старым
строкам проставляем done_at из created_at: каждая из них была именно
отметкой ученика, и потерять её значило бы вернуть детям уже сделанные
задания в список «Сделать».
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def student_marks_keep_their_time(apps, schema_editor):
    HomeworkMark = apps.get_model("journal", "HomeworkMark")
    HomeworkMark.objects.filter(done_at__isnull=True).update(done_at=models.F("created_at"))


def back_to_bare_marks(apps, schema_editor):
    """Обратно ставить нечего: done_at исчезает вместе с колонкой."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_alter_auditlog_action"),
        ("journal", "0011_homeworkfile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="homeworkmark",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "домашнее задание ученика",
                "verbose_name_plural": "домашние задания учеников",
            },
        ),
        migrations.AddField(
            model_name="homeworkmark",
            name="checked_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="педагог проверил"
            ),
        ),
        migrations.AddField(
            model_name="homeworkmark",
            name="checked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="homework_checks",
                to=settings.AUTH_USER_MODEL,
                verbose_name="кто проверил",
            ),
        ),
        migrations.AddField(
            model_name="homeworkmark",
            name="comment",
            field=models.TextField(blank=True, verbose_name="что сказал педагог"),
        ),
        migrations.AddField(
            model_name="homeworkmark",
            name="done_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="ученик отметил"
            ),
        ),
        migrations.AddField(
            model_name="homeworkmark",
            name="verdict",
            field=models.CharField(
                blank=True,
                choices=[("accepted", "зачтено"), ("redo", "нужно доделать")],
                max_length=16,
                verbose_name="итог проверки",
            ),
        ),
        migrations.RunPython(
            student_marks_keep_their_time, back_to_bare_marks, elidable=True
        ),
        migrations.AddIndex(
            model_name="homeworkmark",
            index=models.Index(
                fields=["organization", "homework", "checked_at"],
                name="journal_hom_organiz_75400c_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="homeworkmark",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("checked_at__isnull", True), ("verdict", "")),
                    models.Q(
                        ("checked_at__isnull", False),
                        models.Q(("verdict", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="homework_mark_verdict_with_check",
            ),
        ),
    ]
