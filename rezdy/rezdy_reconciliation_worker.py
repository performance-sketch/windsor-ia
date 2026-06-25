"""
Rezdy Reconciliation Worker
============================
Busca pedidos recentes na Rezdy via API e faz upsert em fact_rezdy_bookings.
Corrige status, cancelamentos e pagamentos que chegam com atraso.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.app.config import get_settings
from apps.api.app.models.facts import FactRezdyBooking, FactSyncHealth
from connectors.rezdy.client import RezdyClient
from connectors.rezdy.schemas import RezdyBooking

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


def _booking_to_values(booking: RezdyBooking, raw_event_id: str | None = None) -> dict:
    return dict(
        order_number=booking.orderNumber,
        order_status=booking.status,
        product_code=booking.product_code,
        product_name=booking.product_name,
        customer_id=booking.customer.id if booking.customer else None,
        customer_name=booking.customer.full_name if booking.customer else None,
        customer_email=booking.customer.email if booking.customer else None,
        customer_phone=booking.customer.phone if booking.customer else None,
        booking_created_at=booking.created_at,
        booking_updated_at=booking.updated_at,
        session_start_at=booking.primary_item.session_start if booking.primary_item else None,
        session_end_at=booking.primary_item.session_end if booking.primary_item else None,
        quantity=booking.total_pax,
        gross_revenue=booking.totalAmount,
        net_revenue=booking.totalAmount,
        payment_status=booking.paymentOption,
        source_channel=booking.source,
        utm_source=booking.get_utm("utm_source"),
        utm_medium=booking.get_utm("utm_medium"),
        utm_campaign=booking.get_utm("utm_campaign"),
        utm_content=booking.get_utm("utm_content"),
        utm_term=booking.get_utm("utm_term"),
        raw_payload=booking.model_dump(mode="json"),
        updated_at=datetime.now(tz=timezone.utc),
    )


async def _upsert_booking(session: AsyncSession, booking: RezdyBooking) -> None:
    values = _booking_to_values(booking)
    stmt = (
        pg_insert(FactRezdyBooking)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["order_number"],
            set_={k: v for k, v in values.items() if k != "order_number"},
        )
    )
    await session.execute(stmt)


async def run_rezdy_reconciliation(lookback_days: int | None = None) -> None:
    lookback = lookback_days or settings.rezdy_reconciliation_lookback_days
    date_start = date.today() - timedelta(days=lookback)
    date_end = date.today()

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    client = RezdyClient(api_key=settings.rezdy_api_key, base_url=settings.rezdy_base_url)

    async with SessionLocal() as session:
        sync_record = FactSyncHealth(
            source="rezdy",
            sync_type=f"reconciliation_{lookback}d",
            started_at=datetime.now(tz=timezone.utc),
            status="running",
        )
        session.add(sync_record)
        await session.commit()

        processed = failed = 0

        try:
            async for booking in client.get_all_bookings(date_start=date_start, date_end=date_end):
                try:
                    await _upsert_booking(session, booking)
                    processed += 1
                except Exception as exc:
                    logger.error("Failed to upsert booking %s: %s", booking.orderNumber, exc)
                    failed += 1

                if processed % 100 == 0 and processed > 0:
                    await session.commit()
                    logger.info("Rezdy reconciliation progress: %d bookings", processed)

            await session.commit()
            sync_record.status = "success"

        except Exception as exc:
            logger.exception("Rezdy reconciliation failed: %s", exc)
            sync_record.status = "error"
            sync_record.error_message = str(exc)[:500]
        finally:
            sync_record.finished_at = datetime.now(tz=timezone.utc)
            sync_record.records_processed = processed
            sync_record.records_failed = failed
            await session.commit()

    await engine.dispose()
    logger.info("Rezdy reconciliation done processed=%d failed=%d", processed, failed)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback-days", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run_rezdy_reconciliation(args.lookback_days))
