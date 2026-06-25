CREATE OR REPLACE VIEW v_rezdy_bookings_daily AS
SELECT
    DATE(booking_created_at)                                                         AS booking_date,
    product_code,
    product_name,
    COUNT(*)                                                                          AS bookings_created,
    COUNT(*) FILTER (WHERE order_status = 'CONFIRMED')                              AS bookings_confirmed,
    COUNT(*) FILTER (WHERE order_status IN ('CANCELLED','ABANDONED_CART'))           AS bookings_cancelled,
    COALESCE(SUM(gross_revenue), 0)                                                  AS gross_revenue,
    COALESCE(SUM(gross_revenue) FILTER (WHERE order_status = 'CONFIRMED'), 0)       AS confirmed_revenue,
    COALESCE(SUM(quantity), 0)                                                       AS total_pax,

    CASE
        WHEN COUNT(*) > 0
        THEN ROUND(COUNT(*) FILTER (WHERE order_status IN ('CANCELLED','ABANDONED_CART'))::numeric / COUNT(*), 4)
    END                                                                               AS cancellation_rate,

    CASE
        WHEN COUNT(*) FILTER (WHERE order_status = 'CONFIRMED') > 0
        THEN ROUND(
            SUM(gross_revenue) FILTER (WHERE order_status = 'CONFIRMED') /
            COUNT(*) FILTER (WHERE order_status = 'CONFIRMED'),
            2
        )
    END                                                                               AS avg_ticket

FROM fact_rezdy_bookings
GROUP BY DATE(booking_created_at), product_code, product_name
ORDER BY booking_date DESC;
