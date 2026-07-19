from enum import Enum as PythonEnum

from sqlalchemy import Enum


def enum_type(enum_class: type[PythonEnum]) -> Enum:
    return Enum(
        enum_class,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )
