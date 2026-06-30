# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

"""Telemetry categories for OpenRAG backend."""


class Category:
    """Telemetry event categories."""
    
    # Application lifecycle
    APPLICATION_STARTUP = "APPLICATION_STARTUP"
    APPLICATION_SHUTDOWN = "APPLICATION_SHUTDOWN"
    
    # Service initialization
    SERVICE_INITIALIZATION = "SERVICE_INITIALIZATION"
    
    # OpenSearch operations
    OPENSEARCH_SETUP = "OPENSEARCH_SETUP"
    OPENSEARCH_INDEX = "OPENSEARCH_INDEX"
    
    # Document operations
    DOCUMENT_INGESTION = "DOCUMENT_INGESTION"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    
    # Authentication
    AUTHENTICATION = "AUTHENTICATION"
    
    # Connector operations
    CONNECTOR_OPERATIONS = "CONNECTOR_OPERATIONS"
    
    # Flow operations
    FLOW_OPERATIONS = "FLOW_OPERATIONS"
    
    # Task operations
    TASK_OPERATIONS = "TASK_OPERATIONS"
    
    # Chat operations
    CHAT_OPERATIONS = "CHAT_OPERATIONS"
    
    # Error conditions
    ERROR_CONDITIONS = "ERROR_CONDITIONS"
    
    # Settings operations
    SETTINGS_OPERATIONS = "SETTINGS_OPERATIONS"
    
    # Onboarding
    ONBOARDING = "ONBOARDING"

