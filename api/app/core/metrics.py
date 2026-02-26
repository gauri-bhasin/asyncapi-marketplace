from prometheus_client import Gauge


events_ingested_total = Gauge("events_ingested_total", "Total ingested events in storage")
ws_active_subscriptions = Gauge("ws_active_subscriptions", "Active websocket subscriptions")
dlq_events_total = Gauge("dlq_events_total", "Total DLQ events")
connector_errors_total = Gauge("connector_errors_total", "Connector error count from audit logs")
