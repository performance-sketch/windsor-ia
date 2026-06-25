from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, AsyncIterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .schemas import RezdyBooking

logger = logging.getLogger(__name__)


class RezdyAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Rezdy API {status_code}: {message}")


class RezdyClient:
    def __init__(self, api_key: str, base_url: str = "https://api.rezdy.com/v1", timeout: float = 20.0) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @retry(
        retry=retry_if_exception_type((RezdyAPIError, httpx.TimeoutException)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = {"apiKey": self._api_key, **(params or {})}
        url = f"{self._base}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=merged)

        if resp.status_code in (500, 502, 503, 504):
            raise RezdyAPIError(resp.status_code, resp.text[:200])

        if not resp.is_success:
            raise RezdyAPIError(resp.status_code, resp.text[:200])

        return resp.json()

    async def get_bookings(
        self,
        date_start: date | None = None,
        date_end: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RezdyBooking]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if date_start:
            params["orderDateStart"] = date_start.isoformat()
        if date_end:
            params["orderDateEnd"] = date_end.isoformat()

        data = await self._get("bookings", params)
        return [RezdyBooking.model_validate(b) for b in data.get("bookings", [])]

    async def get_all_bookings(
        self,
        date_start: date | None = None,
        date_end: date | None = None,
        page_size: int = 100,
        max_records: int = 10_000,
    ) -> AsyncIterator[RezdyBooking]:
        offset = 0
        fetched = 0

        while fetched < max_records:
            batch = await self.get_bookings(date_start, date_end, limit=page_size, offset=offset)
            if not batch:
                break
            for b in batch:
                yield b
                fetched += 1
            if len(batch) < page_size:
                break
            offset += page_size
            time.sleep(0.1)

        logger.info("get_all_bookings fetched=%d", fetched)

    async def get_booking(self, order_number: str) -> RezdyBooking | None:
        try:
            data = await self._get(f"bookings/{order_number}")
            raw = data.get("booking") or (data.get("bookings") or [None])[0]
            if raw:
                return RezdyBooking.model_validate(raw)
        except RezdyAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        return None

    async def get_products(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        data = await self._get("products", {"limit": limit, "offset": offset})
        return data.get("products", [])
