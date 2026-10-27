from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.services.gst import money


class Money(TypeDecorator):
    """Persist money as a decimal string so SQLite does not turn it into float."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(money(Decimal(str(value))))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return money(Decimal(str(value)))
