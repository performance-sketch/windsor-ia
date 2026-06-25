from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RezdyCustomer(BaseModel):
    id: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    email: str | None = None
    phone: str | None = None

    @property
    def full_name(self) -> str:
        parts = [self.firstName or "", self.lastName or ""]
        return " ".join(p for p in parts if p).strip()


class RezdyQuantity(BaseModel):
    optionLabel: str | None = None
    optionPrice: float | None = None
    value: int = 0


class RezdySessionItem(BaseModel):
    productCode: str | None = None
    productName: str | None = None
    startTimeLocal: str | None = None
    endTimeLocal: str | None = None
    quantities: list[RezdyQuantity] = Field(default_factory=list)
    amount: float | None = None
    unitPrice: float | None = None

    @property
    def session_start(self) -> datetime | None:
        if self.startTimeLocal:
            try:
                return datetime.fromisoformat(self.startTimeLocal.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @property
    def session_end(self) -> datetime | None:
        if self.endTimeLocal:
            try:
                return datetime.fromisoformat(self.endTimeLocal.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @property
    def total_pax(self) -> int:
        return sum(q.value for q in self.quantities)


class RezdyBooking(BaseModel):
    orderNumber: str
    status: str | None = None
    totalAmount: float = 0
    totalDue: float = 0
    totalPaid: float = 0
    paymentOption: str | None = None
    customer: RezdyCustomer | None = None
    items: list[RezdySessionItem] = Field(default_factory=list)
    vouchers: list[Any] = Field(default_factory=list)
    coupon: str | None = None
    dateCreated: str | None = None
    dateUpdated: str | None = None
    comments: str | None = None
    internalNotes: str | None = None
    source: str | None = None
    resellerId: str | None = None

    # UTM / tracking fields (quando enviados via campo personalizado)
    fields_: list[dict[str, Any]] = Field(default_factory=list, alias="fields")

    model_config = {"populate_by_name": True}

    @field_validator("totalAmount", "totalDue", "totalPaid", mode="before")
    @classmethod
    def coerce_float(cls, v: Any) -> float:
        if v is None:
            return 0.0
        return float(v)

    @property
    def created_at(self) -> datetime | None:
        if self.dateCreated:
            try:
                return datetime.fromisoformat(self.dateCreated.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @property
    def updated_at(self) -> datetime | None:
        if self.dateUpdated:
            try:
                return datetime.fromisoformat(self.dateUpdated.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @property
    def primary_item(self) -> RezdySessionItem | None:
        return self.items[0] if self.items else None

    @property
    def product_code(self) -> str | None:
        return self.primary_item.productCode if self.primary_item else None

    @property
    def product_name(self) -> str | None:
        return self.primary_item.productName if self.primary_item else None

    @property
    def total_pax(self) -> int:
        return sum(item.total_pax for item in self.items)

    def get_utm(self, key: str) -> str | None:
        for f in self.fields_:
            if f.get("label", "").lower() == key.lower():
                return f.get("value")
        return None


class RezdyWebhookPayload(BaseModel):
    event: str
    booking: RezdyBooking | None = None
    orderNumber: str | None = None

    @property
    def effective_order_number(self) -> str | None:
        if self.booking:
            return self.booking.orderNumber
        return self.orderNumber
