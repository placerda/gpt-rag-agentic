import os
import time
import logging
import asyncio
from typing import Any, Dict, List, Optional, Annotated
import aiohttp
from azure.identity import ChainedTokenCredential, ManagedIdentityCredential, AzureCliCredential
from .types import MeasuresList, MeasureItem
from semantic_kernel.skill_definition import sk_function

# Helper function (not decorated, remains local)
async def _perform_search(body: Dict[str, Any], search_index: str) -> Dict[str, Any]:
    search_service = os.getenv("AZURE_SEARCH_SERVICE")
    if not search_service:
        raise Exception("AZURE_SEARCH_SERVICE environment variable is not set.")
    search_api_version = os.getenv("AZURE_SEARCH_API_VERSION", "2024-07-01")
    search_endpoint = (
        f"https://{search_service}.search.windows.net/indexes/{search_index}/docs/search"
        f"?api-version={search_api_version}"
    )
    try:
        credential = ChainedTokenCredential(
            ManagedIdentityCredential(),
            AzureCliCredential()
        )
        azure_search_scope = "https://search.azure.com/.default"
        token = credential.get_token(azure_search_scope).token
    except Exception as e:
        logging.error("Error obtaining Azure Search token.", exc_info=True)
        raise Exception("Failed to obtain Azure Search token.") from e
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(search_endpoint, headers=headers, json=body) as response:
                if response.status >= 400:
                    text = await response.text()
                    error_message = f"Status code: {response.status}. Error: {text}"
                    logging.error(f"[measures] {error_message}")
                    raise Exception(error_message)
                return await response.json()
        except Exception as e:
            logging.error("Error during the search HTTP request.", exc_info=True)
            raise Exception("Failed to execute search query.") from e

@sk_function(description="Retrieves measures info from Azure AI Search for the given datasource.")
async def measures_retrieval(
    datasource: Annotated[str, "Name of the target datasource"]
) -> MeasuresList:
    search_index = "nl2sql-measures"
    safe_datasource = datasource.replace("'", "''")
    filter_expression = f"datasource eq '{safe_datasource}'"
    body = {
        "search": "*",
        "filter": filter_expression,
        "select": "name, description, datasource, type, source_table, data_type, source_model",
        "top": 1000
    }
    logging.info(f"[measures] Querying Azure AI Search for measures in datasource '{datasource}'")
    measures_info: List[MeasureItem] = []
    error_message: Optional[str] = None
    try:
        start_time = time.time()
        result = await _perform_search(body, search_index)
        elapsed = round(time.time() - start_time, 2)
        logging.info(f"[measures] Finished querying measures in {elapsed} seconds")
        for doc in result.get("value", []):
            measure_item = MeasureItem(
                name=doc.get("name", ""),
                description=doc.get("description", ""),
                datasource=doc.get("datasource", ""),
                type=doc.get("type", None),
                source_table=doc.get("source_table", None),
                data_type=doc.get("data_type", None),
                source_model=doc.get("source_model", None)
            )
            measures_info.append(measure_item)
    except Exception as e:
        error_message = str(e)
        logging.error(f"[measures] Error querying measures: {error_message}")
    if not measures_info:
        return MeasuresList(
            measures=[],
            error=f"No datasource with name '{datasource}' was found. {error_message or ''}".strip()
        )
    return MeasuresList(measures=measures_info, error=error_message)
