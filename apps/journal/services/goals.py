"""
Путь к цели.

Цель вроде «разобраться с тригонометрией» невыполнима: за неё нельзя
взяться сегодня и нельзя отметить сделанной. Поэтому цель раскладывается
на шаги, а движение по ним показывается как путь: пройденное — позади и
зелёное, спутник стоит там, докуда дошли.

Смысл не в геймификации ради неё самой. Подросток бросает цель не потому,
что ленив, а потому что не видит, сдвинулся ли он вообще. Путь отвечает
ровно на этот вопрос — и отвечает честно: шаги придумывает сам ученик, и
никто, кроме него, их не отмечает.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.journal.models import Goal, GoalStep

STEP_LIMIT = 12
TITLE_LIMIT = 200

# Похвала за пройденный шаг. Разная — одна и та же на десятый раз читается
# как автоответчик, а не как «тебя заметили».
PRAISE = [
    "Первый шаг сделан — дальше проще.",
    "Ещё один позади. Так и набирается путь.",
    "Половина пути позади — это уже немало.",
    "Осталось немного — видно край.",
    "Последний шаг. Дожать — и цель ваша.",
]
DONE_PRAISE = "Цель достигнута. Целиком, своим ходом."


@dataclass(frozen=True)
class Path:
    """Путь к цели: сколько шагов, сколько пройдено и где стоит спутник."""

    total: int
    done: int

    @property
    def percent(self) -> int:
        if not self.total:
            return 0
        return int(round(self.done * 100 / self.total))

    @property
    def is_complete(self) -> bool:
        return bool(self.total) and self.done >= self.total

    @property
    def praise(self) -> str:
        if not self.done:
            return ""
        if self.is_complete:
            return DONE_PRAISE
        index = min(len(PRAISE) - 1, int(self.percent / 100 * len(PRAISE)))
        return PRAISE[index]


def path_of(goal: Goal) -> Path:
    """
    Путь по шагам цели.

    Считаем по уже загруженным шагам, если они загружены: у цели их
    единицы, а запрос на каждую цель в списке — это тот самый N+1.
    """
    steps = goal.steps.all()
    return Path(total=len(steps), done=sum(1 for step in steps if step.is_done))


@transaction.atomic
def set_steps(*, goal: Goal, titles: list[str]) -> list[GoalStep]:
    """
    Переписать шаги цели.

    Отметки о выполнении сохраняются по тексту шага: ученик правит
    формулировку, а не начинает путь заново. Совпал текст — совпала и
    отметка.
    """
    titles = [title.strip()[:TITLE_LIMIT] for title in titles if title and title.strip()]
    if len(titles) > STEP_LIMIT:
        raise ValidationError(
            f"Шагов не больше {STEP_LIMIT}. Длинный список — это уже не путь, а расписание."
        )

    done_before = {
        step.title: step.done_at for step in goal.steps.all() if step.done_at is not None
    }
    goal.steps.all().delete()
    steps = [
        GoalStep(
            organization=goal.organization, goal=goal, title=title, position=index,
            done_at=done_before.get(title),
        )
        for index, title in enumerate(titles, start=1)
    ]
    GoalStep.objects.bulk_create(steps)
    return steps


def toggle_step(step: GoalStep) -> GoalStep:
    """
    Отметить шаг сделанным или снять отметку.

    Снять можно всегда: отметить лишнее — обычное дело, а невозможность
    исправить учит врать журналу, а не себе.
    """
    step.done_at = None if step.is_done else timezone.now()
    step.save(update_fields=["done_at", "updated_at"])
    return step
