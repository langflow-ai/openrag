# Production System Error Logs & Telemetry Dump

```log
2025-05-12T08:34:12.102Z [ERROR] [auth-gateway] Connection failure target=192.168.1.105:5432 status=ERR_CONNECTION_REFUSED trace_id=9f8b4c2a-11e2-4b78-98e3-0c4a51e60021
2025-05-12T08:34:13.411Z [WARN]  [rate-limiter] Client token bucket exhausted ip=10.0.4.12 retry_after_ms=4500
2025-05-12T08:34:15.908Z [FATAL] [storage-node] Disk volume /mnt/data/shard_04 capacity exceeded 98.7% threshold_action=READ_ONLY
2025-05-12T08:35:01.002Z [INFO]  [health-daemon] TCP socket ping host=db-replica-01.internal latency_ms=1.442 status=OK
```

## System Metric Counters
- `http_requests_total{code="500",handler="/api/v1/sync"}`: 1420
- `jvm_gc_pause_seconds_max`: 0.428
- `process_resident_memory_bytes`: 8589934592
- `kernel_network_rx_dropped_packets`: 0
- `gateway_uuid`: 3c9b7402-9844-42f0-9118-289db1fec19a
