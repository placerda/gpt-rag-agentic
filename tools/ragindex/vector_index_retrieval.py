import os
import re
import time
import json
import logging
import asyncio
from typing import Annotated, Optional, List, Dict, Any
from urllib.parse import urlparse
import aiohttp
from azure.identity import ManagedIdentityCredential, AzureCliCredential, ChainedTokenCredential
from connectors import AzureOpenAIClient
from .types import (
    VectorIndexRetrievalResult,
    MultimodalVectorIndexRetrievalResult,
    DataPointsResult,
)
from semantic_kernel.skill_definition import sk_function

async def _get_azure_search_token() -> str:
    try:
        credential = ChainedTokenCredential(
            ManagedIdentityCredential(),
            AzureCliCredential()
        )
        token_obj = await asyncio.to_thread(credential.get_token, "https://search.azure.com/.default")
        return token_obj.token
    except Exception as e:
        logging.error("Error obtaining Azure Search token.", exc_info=True)
        raise Exception("Failed to obtain Azure Search token.") from e

async def _perform_search(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=body) as response:
                if response.status >= 400:
                    text = await response.text()
                    error_message = f"Error {response.status}: {text}"
                    logging.error(f"[_perform_search] {error_message}")
                    raise Exception(error_message)
                return await response.json()
        except Exception as e:
            logging.error("Error during asynchronous HTTP request.", exc_info=True)
            raise Exception("Failed to execute search query.") from e

@sk_function(description="Performs a vector search against Azure Cognitive Search and returns results as a concatenated string.")
async def vector_index_retrieve(
    input: Annotated[str, "An optimized query string based on the user's ask"],
    security_ids: str = 'anonymous'
) -> VectorIndexRetrievalResult:
    aoai = AzureOpenAIClient()
    search_top_k = os.getenv('AZURE_SEARCH_TOP_K', 3)
    search_approach = os.getenv('AZURE_SEARCH_APPROACH', 'hybrid')
    VECTOR_SEARCH_APPROACH = 'vector'
    TERM_SEARCH_APPROACH = 'term'
    HYBRID_SEARCH_APPROACH = 'hybrid'
    search_service = os.getenv('AZURE_SEARCH_SERVICE')
    search_index = os.getenv('AZURE_SEARCH_INDEX', 'ragindex')
    search_api_version = os.getenv('AZURE_SEARCH_API_VERSION', '2024-07-01')
    search_results: List[str] = []
    error_message: Optional[str] = None
    search_query = input
    try:
        start_time = time.time()
        logging.info(f"[vector_index_retrieve] Generating embeddings for query: {search_query}")
        embeddings_query = await asyncio.to_thread(aoai.get_embeddings, search_query)
        response_time = round(time.time() - start_time, 2)
        logging.info(f"[vector_index_retrieve] Embeddings generated in {response_time} seconds")
        azure_search_token = await _get_azure_search_token()
        body: Dict[str, Any] = {
            "select": "title, content, url, filepath, chunk_id",
            "top": search_top_k
        }
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
        filter_str = (
            f"metadata_security_id/any(g:search.in(g, '{security_ids}')) "
            "or not metadata_security_id/any()"
        )
        body["filter"] = filter_str
        logging.debug(f"[vector_index_retrieve] Using filter: {filter_str}")
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {azure_search_token}'
        }
        search_url = (
            f"https://{search_service}.search.windows.net/indexes/{search_index}/docs/search"
            f"?api-version={search_api_version}"
        )
        start_time = time.time()
        response_json = await _perform_search(search_url, headers, body)
        elapsed = round(time.time() - start_time, 2)
        logging.info(f"[vector_index_retrieve] Search executed in {elapsed} seconds")
        if response_json.get('value'):
            logging.info(f"[vector_index_retrieve] Retrieved {len(response_json['value'])} documents")
            for doc in response_json['value']:
                url = doc.get('url', '')
                uri = re.sub(r'https://[^/]+\.blob\.core\.windows\.net', '', url)
                content_str = doc.get('content', '').strip()
                search_results.append(f"{uri}: {content_str}\n")
        else:
            logging.info("[vector_index_retrieve] No documents found.")
    except Exception as e:
        error_message = f"Exception occurred: {e}"
        logging.error(f"[vector_index_retrieve] {error_message}", exc_info=True)
    sources = ' '.join(search_results)
    return VectorIndexRetrievalResult(result=sources, error=error_message)

@sk_function(description="Performs multimodal retrieval: returns separate lists for texts and related image URLs along with captions.")
async def multimodal_vector_index_retrieve(
    input: Annotated[str, "An optimized query string based on the user's ask"],
    security_ids: str = 'anonymous'
) -> MultimodalVectorIndexRetrievalResult:
    aoai = AzureOpenAIClient()
    search_top_k = int(os.getenv('AZURE_SEARCH_TOP_K', 3))
    search_approach = os.getenv('AZURE_SEARCH_APPROACH', 'vector')
    semantic_search_config = os.getenv('AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG', 'my-semantic-config')
    search_service = os.getenv('AZURE_SEARCH_SERVICE')
    search_index = os.getenv('AZURE_SEARCH_INDEX', 'ragindex')
    search_api_version = os.getenv('AZURE_SEARCH_API_VERSION', '2024-07-01')
    use_semantic = os.getenv('AZURE_SEARCH_USE_SEMANTIC', 'false').lower() == 'true'
    logging.info(f"[multimodal_vector_index_retrieve] Received input: {input}")
    text_results: List[str] = []
    image_urls: List[List[str]] = []
    captions: List[List[str]] = []
    error_message: Optional[str] = None
    try:
        start_time = time.time()
        embeddings_query = await asyncio.to_thread(aoai.get_embeddings, input)
        embedding_time = round(time.time() - start_time, 2)
        logging.info(f"[multimodal_vector_index_retrieve] Embeddings generated in {embedding_time} seconds")
    except Exception as e:
        error_message = f"Error generating embeddings: {e}"
        logging.error(f"[multimodal_vector_index_retrieve] {error_message}", exc_info=True)
        return MultimodalVectorIndexRetrievalResult(
            texts=[],
            images=[],
            captions=[],
            error=error_message
        )
    try:
        azure_search_token = await _get_azure_search_token()
    except Exception as e:
        error_message = f"Error acquiring Azure Search token: {e}"
        logging.error(f"[multimodal_vector_index_retrieve] {error_message}", exc_info=True)
        return MultimodalVectorIndexRetrievalResult(
            texts=[],
            images=[],
            captions=[],
            error=error_message
        )
    body: Dict[str, Any] = {
        "select": "title, content, filepath, url, imageCaptions, relatedImages",
        "top": search_top_k,
        "vectorQueries": [
            {
                "kind": "vector",
                "vector": embeddings_query,
                "fields": "contentVector",
                "k": int(search_top_k)
            },
            {
                "kind": "vector",
                "vector": embeddings_query,
                "fields": "captionVector",
                "k": int(search_top_k)
            }
        ]
    }
    if use_semantic and search_approach != "vector":
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = semantic_search_config
    filter_str = (
        f"metadata_security_id/any(g:search.in(g, '{security_ids}')) "
        "or not metadata_security_id/any()"
    )
    body["filter"] = filter_str
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {azure_search_token}'
    }
    search_url = (
        f"https://{search_service}.search.windows.net"
        f"/indexes/{search_index}/docs/search"
        f"?api-version={search_api_version}"
    )
    try:
        start_time = time.time()
        response_json = await _perform_search(search_url, headers, body)
        response_time = round(time.time() - start_time, 2)
        logging.info(f"[multimodal_vector_index_retrieve] Search executed in {response_time} seconds")
        for doc in response_json.get('value', []):
            content = doc.get('content', '')
            str_captions = doc.get('imageCaptions', '')
            captions.append(extract_captions(str_captions))
            url = doc.get('url', '')
            uri = re.sub(r'https://[^/]+\.blob\.core\.windows\.net', '', url)
            text_results.append(f"{uri}: {content.strip()}")
            image_urls.append(doc.get('relatedImages', []))
    except Exception as e:
        error_message = f"Exception in retrieval: {e}"
        logging.error(f"[multimodal_vector_index_retrieve] {error_message}", exc_info=True)
    return MultimodalVectorIndexRetrievalResult(
        texts=text_results,
        images=image_urls,
        captions=captions,
        error=error_message
    )

def extract_captions(str_captions):
    pattern = r"\[.*?\]:\s(.*?)(?=\[.*?\]:|$)"
    matches = re.findall(pattern, str_captions, re.DOTALL)
    return [match.strip() for match in matches]

def replace_image_filenames_with_urls(content: str, related_images: list) -> str:
    for image_url in related_images:
        logging.debug(f"[multimodal_vector_index_retrieve] image_url: {image_url}.")
        parsed_url = urlparse(image_url)
        image_path = parsed_url.path.lstrip('/')
        logging.debug(f"[multimodal_vector_index_retrieve] image_path: {image_path}.")
        content = content.replace(image_path, image_url)
        logging.debug(f"[multimodal_vector_index_retrieve] updated content: {content}.")
    return content

@sk_function(description="Extracts data points from a chat log.")
def get_data_points_from_chat_log(chat_log: list) -> DataPointsResult:
    request_call_id_pattern = re.compile(r"id='([^']+)'")
    request_function_name_pattern = re.compile(r"name='([^']+)'")
    exec_call_id_pattern = re.compile(r"call_id='([^']+)'")
    exec_content_pattern = re.compile(r"content='(.+?)', call_id=", re.DOTALL)
    allowed_extensions = ['vtt', 'xlsx', 'xls', 'pdf', 'docx', 'pptx', 'png', 'jpeg', 'jpg', 'bmp', 'tiff']
    filename_pattern = re.compile(
        rf"([^\s:]+\.(?:{'|'.join(allowed_extensions)})\s*:\s*.*?)(?=[^\s:]+\.(?:{'|'.join(allowed_extensions)})\s*:|$)",
        re.IGNORECASE | re.DOTALL
    )
    relevant_call_ids = set()
    data_points = []
    for msg in chat_log:
        if msg["message_type"] == "ToolCallRequestEvent":
            content = msg["content"][0]
            call_id_match = request_call_id_pattern.search(content)
            function_name_match = request_function_name_pattern.search(content)
            if call_id_match and function_name_match:
                if function_name_match.group(1) == "vector_index_retrieve_wrapper":
                    relevant_call_ids.add(call_id_match.group(1))
        elif msg["message_type"] == "ToolCallExecutionEvent":
            content = msg["content"][0]
            call_id_match = exec_call_id_pattern.search(content)
            if call_id_match and call_id_match.group(1) in relevant_call_ids:
                content_part_match = exec_content_pattern.search(content)
                if not content_part_match:
                    continue
                content_part = content_part_match.group(1)
                try:
                    parsed = json.loads(content_part)
                    texts = parsed.get("texts", [])
                except json.JSONDecodeError:
                    texts = [re.split(r'["\']images["\']\s*:\s*\[', content_part, 1, re.IGNORECASE)[0]]
                for text in texts:
                    text = bytes(text, "utf-8").decode("unicode_escape")
                    for match in filename_pattern.findall(text):
                        extracted = match.strip(" ,\\\"").lstrip("[").rstrip("],")
                        if extracted:
                            data_points.append(extracted)
    return DataPointsResult(data_points=data_points)
