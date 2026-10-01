# Apex Omega — FinTech OS

Ultra-low-latency trading infrastructure with FIX protocol, venue connectors, feed handling, order book, and risk engine.

## Components
- **Core**: Orchestrator, config, logging, metrics, health checks
- **FIX Protocol**: 4.2/4.4/5.0 sessions, message router, builder, store, heartbeat
- **Venues**: Bloomberg B-PIPE, EMSX, MarketAxess adapters
- **Feed**: Multi-venue ingestion (100K+ events/sec), normalizer, filter, statistics
- **Order Book**: Price-time priority matching (10K+ orders/sec)
- **Risk**: Pre-trade checks, kill switch (MiFID II Art 16), audit trail
- **Security**: Zero-trust, mTLS, SPIFFE/SPIRE, RBAC/ABAC, secrets management
- **Infrastructure**: Docker, Kubernetes, CI/CD

## Tests
~1,500 tests, TDD-enforced.

## License
AGPL-3.0
