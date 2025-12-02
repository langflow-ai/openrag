"""Telemetry message IDs for OpenRAG backend.

All message IDs start with ORB_ (OpenRAG Backend) followed by descriptive text.
Format: ORB_<CATEGORY>_<ACTION>[_<STATUS>]
"""


class MessageId:
    """Telemetry message IDs."""
    
    # Category: APPLICATION_STARTUP ------------------------------------------->
    
    # Message: Application started successfully
    ORB_APP_STARTED = "ORB_APP_STARTED"
    # Message: Application startup initiated
    ORB_APP_START_INIT = "ORB_APP_START_INIT"
    # Message: Application shutdown initiated
    ORB_APP_SHUTDOWN = "ORB_APP_SHUTDOWN"
    
    # Category: SERVICE_INITIALIZATION ----------------------------------------->
    
    # Message: Services initialized successfully
    ORB_SVC_INIT_SUCCESS = "ORB_SVC_INIT_SUCCESS"
    # Message: Service initialization started
    ORB_SVC_INIT_START = "ORB_SVC_INIT_START"
    # Message: Failed to initialize services
    ORB_SVC_INIT_FAILED = "ORB_SVC_INIT_FAILED"
    # Message: Failed to initialize OpenSearch client
    ORB_SVC_OS_CLIENT_FAIL = "ORB_SVC_OS_CLIENT_FAIL"
    # Message: Failed to generate JWT keys
    ORB_SVC_JWT_KEY_FAIL = "ORB_SVC_JWT_KEY_FAIL"
    
    # Category: OPENSEARCH_SETUP ---------------------------------------------->
    
    # Message: OpenSearch connection established
    ORB_OS_CONN_ESTABLISHED = "ORB_OS_CONN_ESTABLISHED"
    # Message: OpenSearch connection failed
    ORB_OS_CONN_FAILED = "ORB_OS_CONN_FAILED"
    # Message: Waiting for OpenSearch to be ready
    ORB_OS_WAITING = "ORB_OS_WAITING"
    # Message: OpenSearch ready check timeout
    ORB_OS_TIMEOUT = "ORB_OS_TIMEOUT"
    
    # Category: OPENSEARCH_INDEX ---------------------------------------------->
    
    # Message: OpenSearch index created successfully
    ORB_OS_INDEX_CREATED = "ORB_OS_INDEX_CREATED"
    # Message: OpenSearch index already exists
    ORB_OS_INDEX_EXISTS = "ORB_OS_INDEX_EXISTS"
    # Message: Failed to create OpenSearch index
    ORB_OS_INDEX_CREATE_FAIL = "ORB_OS_INDEX_CREATE_FAIL"
    # Message: Failed to initialize index
    ORB_OS_INDEX_INIT_FAIL = "ORB_OS_INDEX_INIT_FAIL"
    # Message: Knowledge filters index created
    ORB_OS_KF_INDEX_CREATED = "ORB_OS_KF_INDEX_CREATED"
    # Message: Failed to create knowledge filters index
    ORB_OS_KF_INDEX_FAIL = "ORB_OS_KF_INDEX_FAIL"
    
    # Category: DOCUMENT_INGESTION -------------------------------------------->
    
    # Message: Document ingestion started
    ORB_DOC_INGEST_START = "ORB_DOC_INGEST_START"
    # Message: Document ingestion completed successfully
    ORB_DOC_INGEST_COMPLETE = "ORB_DOC_INGEST_COMPLETE"
    # Message: Document ingestion failed
    ORB_DOC_INGEST_FAILED = "ORB_DOC_INGEST_FAILED"
    # Message: Default documents ingestion started
    ORB_DOC_DEFAULT_START = "ORB_DOC_DEFAULT_START"
    # Message: Default documents ingestion completed
    ORB_DOC_DEFAULT_COMPLETE = "ORB_DOC_DEFAULT_COMPLETE"
    # Message: Default documents ingestion failed
    ORB_DOC_DEFAULT_FAILED = "ORB_DOC_DEFAULT_FAILED"
    
    # Category: DOCUMENT_PROCESSING -------------------------------------------->
    
    # Message: Document processing started
    ORB_DOC_PROCESS_START = "ORB_DOC_PROCESS_START"
    # Message: Document processing completed
    ORB_DOC_PROCESS_COMPLETE = "ORB_DOC_PROCESS_COMPLETE"
    # Message: Document processing failed
    ORB_DOC_PROCESS_FAILED = "ORB_DOC_PROCESS_FAILED"
    # Message: Process pool recreation attempted
    ORB_DOC_POOL_RECREATE = "ORB_DOC_POOL_RECREATE"
    
    # Category: AUTHENTICATION ------------------------------------------------>
    
    # Message: Authentication successful
    ORB_AUTH_SUCCESS = "ORB_AUTH_SUCCESS"
    # Message: Authentication failed
    ORB_AUTH_FAILED = "ORB_AUTH_FAILED"
    # Message: User logged out
    ORB_AUTH_LOGOUT = "ORB_AUTH_LOGOUT"
    # Message: OAuth callback received
    ORB_AUTH_OAUTH_CALLBACK = "ORB_AUTH_OAUTH_CALLBACK"
    # Message: OAuth callback failed
    ORB_AUTH_OAUTH_FAILED = "ORB_AUTH_OAUTH_FAILED"
    
    # Category: CONNECTOR_OPERATIONS ------------------------------------------->
    
    # Message: Connector connection established
    ORB_CONN_CONNECTED = "ORB_CONN_CONNECTED"
    # Message: Connector connection failed
    ORB_CONN_CONNECT_FAILED = "ORB_CONN_CONNECT_FAILED"
    # Message: Connector sync started
    ORB_CONN_SYNC_START = "ORB_CONN_SYNC_START"
    # Message: Connector sync completed
    ORB_CONN_SYNC_COMPLETE = "ORB_CONN_SYNC_COMPLETE"
    # Message: Connector sync failed
    ORB_CONN_SYNC_FAILED = "ORB_CONN_SYNC_FAILED"
    # Message: Connector webhook received
    ORB_CONN_WEBHOOK_RECV = "ORB_CONN_WEBHOOK_RECV"
    # Message: Connector webhook failed
    ORB_CONN_WEBHOOK_FAILED = "ORB_CONN_WEBHOOK_FAILED"
    # Message: Failed to load persisted connections
    ORB_CONN_LOAD_FAILED = "ORB_CONN_LOAD_FAILED"
    
    # Category: FLOW_OPERATIONS ------------------------------------------------>
    
    # Message: Flow backup completed
    ORB_FLOW_BACKUP_COMPLETE = "ORB_FLOW_BACKUP_COMPLETE"
    # Message: Flow backup failed
    ORB_FLOW_BACKUP_FAILED = "ORB_FLOW_BACKUP_FAILED"
    # Message: Flow reset detected
    ORB_FLOW_RESET_DETECTED = "ORB_FLOW_RESET_DETECTED"
    # Message: Flow reset check failed
    ORB_FLOW_RESET_CHECK_FAIL = "ORB_FLOW_RESET_CHECK_FAIL"
    # Message: Settings reapplied after flow reset
    ORB_FLOW_SETTINGS_REAPPLIED = "ORB_FLOW_SETTINGS_REAPPLIED"
    
    # Category: TASK_OPERATIONS ------------------------------------------------>
    
    # Message: Task created successfully
    ORB_TASK_CREATED = "ORB_TASK_CREATED"
    # Message: Task completed successfully
    ORB_TASK_COMPLETE = "ORB_TASK_COMPLETE"
    # Message: Task failed
    ORB_TASK_FAILED = "ORB_TASK_FAILED"
    # Message: Task cancelled
    ORB_TASK_CANCELLED = "ORB_TASK_CANCELLED"
    # Message: Task cancellation failed
    ORB_TASK_CANCEL_FAILED = "ORB_TASK_CANCEL_FAILED"
    
    # Category: CHAT_OPERATIONS ------------------------------------------------>
    
    # Message: Chat request received
    ORB_CHAT_REQUEST_RECV = "ORB_CHAT_REQUEST_RECV"
    # Message: Chat request completed
    ORB_CHAT_REQUEST_COMPLETE = "ORB_CHAT_REQUEST_COMPLETE"
    # Message: Chat request failed
    ORB_CHAT_REQUEST_FAILED = "ORB_CHAT_REQUEST_FAILED"
    
    # Category: ERROR_CONDITIONS ----------------------------------------------->
    
    # Message: Critical error occurred
    ORB_ERROR_CRITICAL = "ORB_ERROR_CRITICAL"
    # Message: Warning condition
    ORB_ERROR_WARNING = "ORB_ERROR_WARNING"
    
    # Category: SETTINGS_OPERATIONS -------------------------------------------->
    
    # Message: Settings updated successfully
    ORB_SETTINGS_UPDATED = "ORB_SETTINGS_UPDATED"
    # Message: Settings update failed
    ORB_SETTINGS_UPDATE_FAILED = "ORB_SETTINGS_UPDATE_FAILED"
    # Message: LLM provider changed
    ORB_SETTINGS_LLM_PROVIDER = "ORB_SETTINGS_LLM_PROVIDER"
    # Message: LLM model changed
    ORB_SETTINGS_LLM_MODEL = "ORB_SETTINGS_LLM_MODEL"
    # Message: Embedding provider changed
    ORB_SETTINGS_EMBED_PROVIDER = "ORB_SETTINGS_EMBED_PROVIDER"
    # Message: Embedding model changed
    ORB_SETTINGS_EMBED_MODEL = "ORB_SETTINGS_EMBED_MODEL"
    # Message: System prompt updated
    ORB_SETTINGS_SYSTEM_PROMPT = "ORB_SETTINGS_SYSTEM_PROMPT"
    # Message: Chunk settings updated
    ORB_SETTINGS_CHUNK_UPDATED = "ORB_SETTINGS_CHUNK_UPDATED"
    # Message: Docling settings updated
    ORB_SETTINGS_DOCLING_UPDATED = "ORB_SETTINGS_DOCLING_UPDATED"
    # Message: Provider credentials updated
    ORB_SETTINGS_PROVIDER_CREDS = "ORB_SETTINGS_PROVIDER_CREDS"
    
    # Category: ONBOARDING ----------------------------------------------------->
    
    # Message: Onboarding started
    ORB_ONBOARD_START = "ORB_ONBOARD_START"
    # Message: Onboarding completed successfully
    ORB_ONBOARD_COMPLETE = "ORB_ONBOARD_COMPLETE"
    # Message: Onboarding failed
    ORB_ONBOARD_FAILED = "ORB_ONBOARD_FAILED"
    # Message: LLM provider selected during onboarding
    ORB_ONBOARD_LLM_PROVIDER = "ORB_ONBOARD_LLM_PROVIDER"
    # Message: LLM model selected during onboarding
    ORB_ONBOARD_LLM_MODEL = "ORB_ONBOARD_LLM_MODEL"
    # Message: Embedding provider selected during onboarding
    ORB_ONBOARD_EMBED_PROVIDER = "ORB_ONBOARD_EMBED_PROVIDER"
    # Message: Embedding model selected during onboarding
    ORB_ONBOARD_EMBED_MODEL = "ORB_ONBOARD_EMBED_MODEL"
    # Message: Sample data ingestion requested
    ORB_ONBOARD_SAMPLE_DATA = "ORB_ONBOARD_SAMPLE_DATA"
    # Message: Configuration marked as edited
    ORB_ONBOARD_CONFIG_EDITED = "ORB_ONBOARD_CONFIG_EDITED"
