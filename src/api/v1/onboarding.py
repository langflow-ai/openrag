"""
Public API v1 Onboarding endpoint.

Provides onboarding configuration setup.
Uses API key authentication.
"""
from fastapi import Depends

from api.settings import OnboardingBody
from dependencies import (
    get_api_key_user_async,
    get_document_service,
    get_flows_service,
    get_knowledge_filter_service,
    get_langflow_file_service,
    get_session_manager,
    get_task_service,
)
from session_manager import User


async def onboarding_endpoint(
    body: OnboardingBody,
    flows_service=Depends(get_flows_service),
    session_manager=Depends(get_session_manager),
    document_service=Depends(get_document_service),
    task_service=Depends(get_task_service),
    langflow_file_service=Depends(get_langflow_file_service),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    user: User = Depends(get_api_key_user_async),
):
    """Initialize OpenRAG with configuration. POST /v1/onboarding"""
    from api.settings import onboarding

    return await onboarding(
        body=body,
        flows_service=flows_service,
        session_manager=session_manager,
        document_service=document_service,
        task_service=task_service,
        langflow_file_service=langflow_file_service,
        knowledge_filter_service=knowledge_filter_service,
        user=user,
    )

