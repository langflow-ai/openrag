from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config

logger = get_logger(__name__)


async def get_openai_models(request, models_service, session_manager):
    """Get available OpenAI models"""
    try:
        # Get API key from query parameters
        query_params = dict(request.query_params)
        api_key = query_params.get("api_key")

        # If no API key provided, try to get it from stored configuration
        if not api_key:
            try:
                config = get_openrag_config()
                api_key = config.provider.api_key
                logger.info(
                    f"Retrieved API key from config: {'yes' if api_key else 'no'}"
                )
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {
                    "error": "OpenAI API key is required either as query parameter or in configuration"
                },
                status_code=400,
            )

        models = await models_service.get_openai_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get OpenAI models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve OpenAI models: {str(e)}"}, status_code=500
        )


async def get_ollama_models(request, models_service, session_manager):
    """Get available Ollama models"""
    try:
        # Get endpoint from query parameters if provided
        query_params = dict(request.query_params)
        endpoint = query_params.get("endpoint")

        # If no API key provided, try to get it from stored configuration
        if not endpoint:
            try:
                config = get_openrag_config()
                endpoint = config.provider.endpoint
                logger.info(
                    f"Retrieved endpoint from config: {'yes' if endpoint else 'no'}"
                )
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {
                    "error": "Endpoint is required either as query parameter or in configuration"
                },
                status_code=400,
            )

        models = await models_service.get_ollama_models(endpoint=endpoint)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Ollama models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve Ollama models: {str(e)}"}, status_code=500
        )


async def get_ibm_models(request, models_service, session_manager):
    """Get available IBM Watson models"""
    try:
        # Get parameters from query parameters if provided
        query_params = dict(request.query_params)
        endpoint = query_params.get("endpoint")
        api_key = query_params.get("api_key")
        project_id = query_params.get("project_id")

        config = get_openrag_config()
        # If no API key provided, try to get it from stored configuration
        if not api_key:
            try:
                api_key = config.provider.api_key
                logger.info(
                    f"Retrieved API key from config: {'yes' if api_key else 'no'}"
                )
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {
                    "error": "OpenAI API key is required either as query parameter or in configuration"
                },
                status_code=400,
            )

        if not endpoint:
            try:
                endpoint = config.provider.endpoint
                logger.info(
                    f"Retrieved endpoint from config: {'yes' if endpoint else 'no'}"
                )
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {
                    "error": "Endpoint is required either as query parameter or in configuration"
                },
                status_code=400,
            )

        if not project_id:
            try:
                project_id = config.provider.project_id
                logger.info(
                    f"Retrieved project ID from config: {'yes' if project_id else 'no'}"
                )
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not project_id:
            return JSONResponse(
                {
                    "error": "Project ID is required either as query parameter or in configuration"
                },
                status_code=400,
            )

        models = await models_service.get_ibm_models(
            endpoint=endpoint, api_key=api_key, project_id=project_id
        )
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get IBM models: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve IBM models: {str(e)}"}, status_code=500
        )
