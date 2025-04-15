import logging
import os
import time
import asyncio
from typing import Optional, Annotated
import aiohttp
from azure.identity import ChainedTokenCredential, ManagedIdentityCredential, AzureCliCredential
from connectors import AzureOpenAIClient
from .types import QueryItem, QueriesRetrievalResult
from semantic_kernel.skill_definition import sk_function

@sk_function(description="Retrieves query details from Azure AI Search based on the user question.")
async def queries_retrieval(
    input: Annotated[str, "The user question"],
    datasource: Annotated[Optional[str], "Target datasource name"] = None,
) -> QueriesRetrievalResult:
    aoai = AzureOpenAIClient()
    VECTOR_SEARCH_APPROACH = 'vector'
    TERM_SEARCH_APPROACH = 'term'
    HYBRID_SEARCH_APPROACH = 'hybrid'
    search_index = os.getenv('NL2SQL_QUERIES_INDEX', 'nl2sql-queries')
    search_approach = os.getenv('AZURE_SEARCH_APPROACH', HYBRID_SEARCH_APPROACH)
    search_top_k = 3
    use_semantic = os.getenv('AZURE_SEARCH_USE_SEMANTIC', "false").lower() == "true"
    semantic_search_config = os.getenv('AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG', 'my-semantic-config')
    search_service = os.getenv('AZURE_SEARCH_SERVICE')
    search_api_version = os.getenv('AZURE_SEARCH_API_VERSION', '2024-07-01')
    search_results = []
    search_query = input
    error_message = None
    try:
        credential = ChainedTokenCredential(
            ManagedIdentityCredential(),
            AzureCliCredential()
        )
        start_time = time.time()
        logging.info(f"[queries_retrieval] Generating question embeddings. Search query: {search_query}")
        embeddings_query = await asyncio.to_thread(aoai.get_embeddings, search_query)
        response_time = round(time.time() - start_time, 2)
        logging.info(f"[queries_retrieval] Finished generating embeddings in {response_time} seconds")
        token_response = await asyncio.to_thread(credential.get_token, "https://search.azure.com/.default")
        azure_search_key = token_response.token
        body = {
            "select": "question, query, reasoning",
            "top": search_top_k
        }
        if datasource:
            safe_datasource = datasource.replace("'", "''")
            body["filter"] = f"datasource eq '{safe_datasource}'"
        if search_approach == TERM_SEARCH_APPROACH:
            body["search"] = search_query
        elif search_approach == VECTOR_SEARCH_APPROACH:
            body["vectorQueries"] = [{
                "kind": "vector",
                "vector": embeddings_query,
                "fields": "contentVector",
                "k": int(search_top_k)
            }]
        elif search_approach == HYBRID_SEARCH_APPROACH:
            body["search"] = search_query
            body["vectorQueries"] = [{
                "kind": "vector",
                "vector": embeddings_query,
                "fields": "contentVector",
                "k": int(search_top_k)
            }]
        if use_semantic and search_approach != VECTOR_SEARCH_APPROACH:
            body["queryType"] = "semantic"
            body["semanticConfiguration"] = semantic_search_config
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {azure_search_key}'
        }
        search_endpoint = (
            f"https://{search_service}.search.windows.net/indexes/{search_index}/docs/search"
            f"?api-version={search_api_version}"
        )
        logging.info(f"[queries_retrieval] Querying Azure AI Search. Search query: {search_query}")
        start_time = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.post(search_endpoint, headers=headers, json=body) as response:
                if response.status >= 400:
                    text = await response.text()
                    error_message = f"Status code: {response.status}. Error: {text if text else 'Unknown error'}."
                    logging.error(f"[queries_retrieval] {error_message}")
                else:
                    json_response = await response.json()
                    if json_response.get('value'):
                        logging.info(f"[queries_retrieval] {len(json_response['value'])} documents retrieved")
                        for doc in json_response['value']:
                            question = doc.get('question', '')
                            query = doc.get('query', '')
                            reasoning = doc.get('reasoning', '')
                            search_results.append({
                                "question": question,
                                "query": query,
                                "reasoning": reasoning
                            })
                    else:
                        logging.info("[queries_retrieval] No documents retrieved")
        response_time = round(time.time() - start_time, 2)
        logging.info(f"[queries_retrieval] Finished querying Azure AI Search in {response_time} seconds")
    except Exception as e:
        error_message = str(e)
        logging.error(f"[queries_retrieval] Error when getting the answer: {error_message}")
    query_items = [QueryItem(**result) for result in search_results]
    return QueriesRetrievalResult(queries=query_items, error=error_message)
