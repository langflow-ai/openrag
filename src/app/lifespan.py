"""Consolidated startup + shutdown lifecycle for the OpenRAG backend.

`run_startup(app)` and `run_shutdown(app)` collapse what previously lived
as three @app.on_event("startup") handlers and three @app.on_event("shutdown")
handlers into one helper each. The factory registers these as on_event
handlers so they fire under FastAPI's lifespan-from-on_event flow, both in
production (the ASGI server drives it) and in tests (which enter/exit
`app.router.lifespan_context(app)` directly, since Starlette 1.x removed the
`app.router.startup()` / `app.router.shutdown()` helpers).
"""

import asyncio

from fastapi import FastAPI

from config.settings import (
    JWT_CLAIMS_CACHE_MAX_SIZE,
    JWT_CLAIMS_CACHE_TTL_SECONDS,
    OPENRAG_BOOTSTRAP_OS_SECURITY_ON_STARTUP,
    RBAC_CACHE_BACKEND,
    RBAC_PERMISSION_CACHE_TTL_SECONDS,
    UVICORN_WORKER_COUNT,
    clients,
    get_openrag_config,
    get_openrag_service_token,
    get_opensearch_password,
    get_opensearch_username,
)
from services.startup_orchestrator import startup_tasks
from utils.logging_config import get_logger, log_bootstrap_env
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def cleanup_subscriptions_proper(services):
    """Cancel all active webhook subscriptions"""
    logger.info("Cancelling active webhook subscriptions")

    try:
        connector_service = services["connector_service"]
        await connector_service.connection_manager.load_connections()

        all_connections = await connector_service.connection_manager.list_connections()
        active_connections = [
            c for c in all_connections if c.is_active and c.config.get("webhook_channel_id")
        ]

        for connection in active_connections:
            try:
                logger.info(
                    "Cancelling subscription for connection",
                    connection_id=connection.connection_id,
                )
                connector = await connector_service.get_connector(connection.connection_id)
                if connector:
                    subscription_id = connection.config.get("webhook_channel_id")
                    await connector.cleanup_subscription(subscription_id)
                    logger.info("Cancelled subscription", subscription_id=subscription_id)
            except Exception as e:
                logger.error(
                    "Failed to cancel subscription",
                    connection_id=connection.connection_id,
                    error=str(e),
                )

        logger.info(
            "Finished cancelling subscriptions",
            subscription_count=len(active_connections),
        )

    except Exception as e:
        logger.error("Failed to cleanup subscriptions", error=str(e))


async def _periodic_backup(services):
    """Run flow backups every 5 minutes once onboarding is complete."""
    while True:
        try:
            await asyncio.sleep(5 * 60)

            config = get_openrag_config()
            if not config.edited:
                logger.debug("Onboarding not completed yet, skipping periodic backup")
                continue

            flows_service = services.get("flows_service")
            if flows_service:
                logger.info("Running periodic flow backup")
                backup_results = await flows_service.backup_all_flows(only_if_changed=True)
                if backup_results["backed_up"]:
                    logger.info(
                        "Periodic backup completed",
                        backed_up=len(backup_results["backed_up"]),
                        skipped=len(backup_results["skipped"]),
                    )
                else:
                    logger.debug(
                        "Periodic backup: no flows changed",
                        skipped=len(backup_results["skipped"]),
                    )
        except asyncio.CancelledError:
            logger.info("Periodic backup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in periodic backup task: {str(e)}")


async def _periodic_webhook_renewal(services):
    """Renew connector webhook subscriptions before they expire.

    Checks immediately at startup (subscriptions may have lapsed while the
    app was down), then on a fixed interval. Provider subscriptions are
    short-lived (Google Drive ~24h, Microsoft Graph 3 days) and go silent
    without renewal.
    """
    from config.settings import (
        WEBHOOK_RENEWAL_INTERVAL_SECONDS,
        WEBHOOK_RENEWAL_THRESHOLD_SECONDS,
    )

    # Let startup_tasks finish loading connections before the first pass
    await asyncio.sleep(60)

    while True:
        try:
            connector_service = services.get("connector_service")
            if connector_service:
                stats = await connector_service.connection_manager.renew_expiring_subscriptions(
                    WEBHOOK_RENEWAL_THRESHOLD_SECONDS
                )
                if stats["renewed"] or stats["failed"]:
                    logger.info("Webhook subscription renewal pass completed", **stats)
                else:
                    logger.debug("Webhook subscription renewal pass completed", **stats)
        except asyncio.CancelledError:
            logger.info("Webhook renewal task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in webhook renewal task: {str(e)}")
        await asyncio.sleep(WEBHOOK_RENEWAL_INTERVAL_SECONDS)


async def run_startup(app: FastAPI):
    """Single source of truth for startup work.

    Expects `app.state.services`, `app.state.mcp_lifespan_ctx`, and
    `app.state.background_tasks` to be set by the factory.
    """
    services = app.state.services
    mcp_lifespan_ctx = getattr(app.state, "mcp_lifespan_ctx", None)

    # Hard-fail if the operator has configured multiple workers. The
    # RBAC permission cache and the OAuth-subject→DB-id cache are
    # both per-process; a second worker silently sees stale
    # permissions for up to OPENRAG_PERM_CACHE_TTL seconds after
    # role mutations. Until the cache moves to a shared backend
    # (Redis), this constraint is real and must be enforced.
    if UVICORN_WORKER_COUNT > 1:
        logger.error(
            "Multi-worker deployment unsupported until cache is "
            "shared across processes. Set UVICORN_WORKERS=1.",
            requested_workers=UVICORN_WORKER_COUNT,
        )
        raise RuntimeError("UVICORN_WORKERS>1 is not supported")
    if RBAC_CACHE_BACKEND not in ("memory",):
        logger.error(
            "Unsupported CACHE_BACKEND. Only 'memory' is wired.",
            requested=RBAC_CACHE_BACKEND,
        )
        raise RuntimeError(f"unsupported CACHE_BACKEND={RBAC_CACHE_BACKEND!r}")
    logger.info(
        "Permission cache configured",
        backend=RBAC_CACHE_BACKEND,
        workers=UVICORN_WORKER_COUNT,
        perm_cache_ttl_s=RBAC_PERMISSION_CACHE_TTL_SECONDS,
    )
    logger.info(
        "JWT claims cache configured",
        backend="memory",
        ttl_s=JWT_CLAIMS_CACHE_TTL_SECONDS,
        maxsize=JWT_CLAIMS_CACHE_MAX_SIZE,
    )

    # RBAC kill-switch visibility. OPENRAG_RBAC_ENFORCE=false makes
    # every authenticated user effectively admin — log loudly so
    # operators see it on every boot. Available in all run modes;
    # the operator owns the trade-off.
    from services.rbac_service import is_rbac_enforced
    from utils.run_mode_utils import get_run_mode

    if is_rbac_enforced():
        logger.info("RBAC enforcement is ON", run_mode=get_run_mode())
    else:
        logger.warning(
            "RBAC enforcement is DISABLED — every authenticated "
            "user has full access via the OPENRAG_RBAC_ENFORCE=false "
            "kill switch.",
            run_mode=get_run_mode(),
        )

    # Open the SQL engine on uvicorn's live loop (NOT the one used by
    # asyncio.run(create_app()) which closed already). All RBAC code
    # uses RBACService's lazy factory that reads db.engine.SessionLocal
    # at call time, so it will pick up the binding we set here.
    try:
        from db.engine import init_engine

        init_engine()
    except Exception as e:
        logger.error("DB engine init failed at startup", error=str(e))
        raise

    # One-shot JSON->DB migration + test-fixture cleanup. Runs once
    # per install, idempotent via migration_status rows.
    try:
        from db.engine import SessionLocal as _SL
        from db.migrations_runtime import run as run_runtime_migration

        if _SL is not None:
            async with _SL() as _session:
                await run_runtime_migration(_session)
                await _session.commit()
    except Exception as e:
        logger.error("Runtime DB migration failed", error=str(e))
        raise

    try:
        wcs = services.get("workspace_config_service")
        if wcs is not None:
            await wcs.hydrate_on_startup()
    except Exception as e:
        logger.error("Workspace config hydration failed at startup", error=str(e))

    await TelemetryClient.send_event(Category.APPLICATION_STARTUP, MessageId.ORB_APP_STARTED)

    # FastMCP requires its own lifespan to be entered before requests
    # arrive so the StreamableHTTPSessionManager task group exists.
    if mcp_lifespan_ctx:
        await mcp_lifespan_ctx.__aenter__()
        logger.info("FastMCP lifespan started")

    log_bootstrap_env(logger, "startup")

    # One-shot OpenSearch security bootstrap driven by the platform's
    # service JWT. Runs synchronously (before startup_tasks) so the
    # admin role mapping is in place before any other startup work
    # talks to OpenSearch. The corresponding call inside startup_tasks
    # is suppressed when this flag is on.
    if OPENRAG_BOOTSTRAP_OS_SECURITY_ON_STARTUP:
        logger.info("OpenSearch security bootstrap enabled - starting")
        from utils.opensearch_init import wait_for_opensearch
        from utils.opensearch_utils import setup_opensearch_security
        from utils.run_mode_utils import (
            is_run_mode_on_prem,
            is_run_mode_oss,
        )

        # Choose the bootstrap OpenSearch client + admin identity, by run mode:
        #   saas    -> platform service token (JWT); admin from its claim
        #   on_prem -> OpenSearch basic auth; OpenSearch username as admin
        #   oss     -> OpenSearch basic auth; OpenSearch username as admin
        if is_run_mode_on_prem() or is_run_mode_oss():
            admin_username = get_opensearch_username()
            opensearch_client = clients.create_basic_opensearch_client(
                admin_username, get_opensearch_password()
            )
            logger.info(
                "OpenSearch security bootstrap: %s mode, using OpenSearch basic auth"
                % ("on_prem" if is_run_mode_on_prem() else "oss"),
                admin_username=admin_username,
            )
        else:
            service_token = get_openrag_service_token()
            if not service_token:
                raise RuntimeError(
                    "OPENRAG_BOOTSTRAP_OS_SECURITY_ON_STARTUP is enabled but "
                    "OPENRAG_SERVICE_TOKEN is not set"
                )
            from auth.ibm_auth import admin_username_from_service_jwt

            admin_username = admin_username_from_service_jwt(service_token)
            if not admin_username:
                raise RuntimeError(
                    "OPENRAG_SERVICE_TOKEN has no 'username' or 'sub' claim; "
                    "cannot bootstrap OpenSearch security"
                )
            opensearch_client = clients.create_opensearch_client_from_jwt(service_token)
            logger.info(
                "OpenSearch security bootstrap: saas mode, using platform service token",
                admin_username=admin_username,
            )
        try:
            logger.info("Verifying OpenSearch readiness before bootstrap")
            await wait_for_opensearch(opensearch_client)
            logger.info("Bootstrapping OpenSearch security", admin_username=admin_username)
            await setup_opensearch_security(opensearch_client, admin_username=admin_username)
            logger.info("OpenSearch security bootstrap completed", admin_username=admin_username)
        finally:
            await opensearch_client.close()
    else:
        logger.info("OpenSearch security bootstrap disabled - skipping (handled in startup_tasks)")

    # Start index initialization in background to avoid blocking OIDC endpoints
    t1 = asyncio.create_task(startup_tasks(services))
    app.state.background_tasks.add(t1)
    t1.add_done_callback(app.state.background_tasks.discard)

    # Start periodic task cleanup scheduler
    services["task_service"].start_cleanup_scheduler()

    # Start periodic flow backup task (every 5 minutes)
    backup_task = asyncio.create_task(_periodic_backup(services))
    app.state.background_tasks.add(backup_task)
    backup_task.add_done_callback(app.state.background_tasks.discard)

    # Start periodic webhook subscription renewal task
    renewal_task = asyncio.create_task(_periodic_webhook_renewal(services))
    app.state.background_tasks.add(renewal_task)
    renewal_task.add_done_callback(app.state.background_tasks.discard)


async def run_shutdown(app: FastAPI):
    """Single source of truth for shutdown work."""
    services = app.state.services
    mcp_lifespan_ctx = getattr(app.state, "mcp_lifespan_ctx", None)

    logger.info("Application shutdown initiated")

    await TelemetryClient.send_event(Category.APPLICATION_SHUTDOWN, MessageId.ORB_APP_SHUTDOWN)

    # Cancel and await our long-lived background tasks (startup_tasks,
    # _periodic_backup) before tearing down the resources they touch
    # (clients, task_service, db engine). Without this, a periodic
    # backup can wake up mid-shutdown and crash on a closed connection
    # or, worse, write partial state to a half-disposed engine.
    background_tasks = list(getattr(app.state, "background_tasks", set()))
    for task in background_tasks:
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
        logger.info("Background tasks cancelled at shutdown", count=len(background_tasks))

    # Drain any pending workspace_config DB-mirror tasks before we
    # tear down the engine. Without this, a save_config triggered
    # right before shutdown can be cancelled mid-write, leaving
    # yaml and DB out of sync.
    try:
        wcs = services.get("workspace_config_service") if isinstance(services, dict) else None
        if wcs is not None:
            await wcs.await_pending_mirrors()
    except Exception as e:  # noqa: BLE001
        logger.error("Error awaiting pending DB mirrors", error=str(e))

    # Stop FastMCP lifespan
    if mcp_lifespan_ctx:
        try:
            await mcp_lifespan_ctx.__aexit__(None, None, None)
            logger.info("FastMCP lifespan stopped")
        except Exception as e:
            logger.error("Error stopping FastMCP lifespan", error=str(e))

    # Gracefully shutdown OpenSearch connection
    try:
        from utils.opensearch_utils import graceful_opensearch_shutdown

        await graceful_opensearch_shutdown(clients.opensearch)
    except Exception as e:
        logger.error("Error during graceful OpenSearch shutdown", error=str(e))

    await cleanup_subscriptions_proper(services)
    # Cleanup task service (cancels background tasks and process pool)
    await services["task_service"].shutdown()
    # Cleanup async clients (this will also close OpenSearch client if not already closed)
    await clients.cleanup()

    # Dispose the SQL engine cleanly. Previously only the (dead) lifespan
    # path did this; the live shutdown_event leaked the engine.
    try:
        from db.engine import dispose_engine

        await dispose_engine()
    except Exception as e:
        logger.error("Error disposing DB engine", error=str(e))

    # Cleanup telemetry client
    from utils.telemetry.client import cleanup_telemetry_client

    await cleanup_telemetry_client()
    logger.info("Application shutdown completed")
