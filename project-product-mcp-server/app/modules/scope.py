"""Reusable ORM predicates for fail-closed environment/owner visibility."""

from platform_database.orm import And, Condition, Operator, Or


def visible(id_environment: int, id_owner: int):
    return And(
        operands=[
            Condition(column="is_deleted", op=Operator.EQ, value=False),
            Or(
                operands=[
                    Condition(column="id_environment", op=Operator.EQ, value=id_environment),
                    Condition(column="id_environment", op=Operator.EQ, value=0),
                ]
            ),
            Or(
                operands=[
                    Condition(column="id_owner", op=Operator.EQ, value=id_owner),
                    Condition(column="id_owner", op=Operator.EQ, value=0),
                ]
            ),
        ]
    )


def writable(id_environment: int, id_owner: int):
    return And(
        operands=[
            Condition(column="is_deleted", op=Operator.EQ, value=False),
            Condition(column="id_environment", op=Operator.EQ, value=id_environment),
            Condition(column="id_owner", op=Operator.EQ, value=id_owner),
        ]
    )


def combine(*predicates):
    return And(operands=[predicate for predicate in predicates if predicate is not None])
