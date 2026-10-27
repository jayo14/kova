from sqlalchemy import JSON, MetaData, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class JSONCompat(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


def load_all_models() -> None:
    """Ensure all SQLAlchemy models are registered in Base.registry."""
    import app.modules.users.models  # noqa: F401
    import app.modules.organizations.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.flows.models  # noqa: F401
    import app.modules.executions.models  # noqa: F401
    import app.modules.executions.event_model  # noqa: F401
    import app.modules.executions.evidence_model  # noqa: F401
    import app.modules.credentials.models  # noqa: F401
    import app.modules.product_graph.models  # noqa: F401
    import app.modules.exploration.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.integrations.models  # noqa: F401
    import app.modules.validation.models  # noqa: F401
    import app.modules.suites.models  # noqa: F401


# Automatically populate registry on module load
try:
    load_all_models()
except Exception:
    # Allow partial imports during initial bootstrapping if necessary
    pass

