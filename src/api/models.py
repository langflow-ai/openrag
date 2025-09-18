from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_openai_models(request, models_service, session_manager):
    """Get available OpenAI models"""
    try:
        models = await models_service.get_openai_models()
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get OpenAI models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve OpenAI models: {str(e)}"},
            status_code=500
        )


async def get_ollama_models(request, models_service, session_manager):
    """Get available Ollama models"""
    try:
        # Get endpoint from query parameters if provided
        query_params = dict(request.query_params)
        endpoint = query_params.get("endpoint")

        models = await models_service.get_ollama_models(endpoint=endpoint)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Ollama models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve Ollama models: {str(e)}"},
            status_code=500
        )


async def get_ibm_models(request, models_service, session_manager):
    """Get available IBM Watson models"""
    try:
        # Get credentials from query parameters or request body if provided
        if request.method == "POST":
            body = await request.json()
            api_key = body.get("api_key")
            endpoint = body.get("endpoint")
            project_id = body.get("project_id")
        else:
            query_params = dict(request.query_params)
            api_key = query_params.get("api_key")
            endpoint = query_params.get("endpoint")
            project_id = query_params.get("project_id")

        models = await models_service.get_ibm_models(
            api_key=api_key,
            endpoint=endpoint,
            project_id=project_id
        )
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get IBM models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve IBM models: {str(e)}"},
            status_code=500
        )