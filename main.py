import os
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from azure.identity import ChainedTokenCredential, ManagedIdentityCredential, AzureCliCredential
from azure.appconfiguration import AzureAppConfigurationClient
from azure.ai.projects import AIProjectClient

from azure.search.documents.aio import SearchClient

log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

credential = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
endpoint = os.getenv("APP_CONFIG_ENDPOINT")
if not endpoint:
    raise EnvironmentError("APP_CONFIG_ENDPOINT must be set")
client = AzureAppConfigurationClient(base_url=endpoint, credential=credential)
for kv in client.list_configuration_settings(label_filter="orchestrator"):
    os.environ[kv.key] = kv.value

app = FastAPI()

@app.post("/orcstream")
async def orcstream_endpoint(request: Request):
    data = await request.json()
    question = data.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="No question in JSON.")

    # load all needed settings
    project_conn_str   = os.getenv("AI_FOUNDRY_PROJECT_CONNECTION_STRING")
    openai_api_version = os.getenv("OPENAI_API_VERSION")
    connection_name    = os.getenv("OPENAI_CONNECTION_NAME")
    deployment_name    = os.getenv("OPENAI_CHAT_DEPLOYMENT")    
    search_service     = os.getenv("SEARCH_SERVICE_NAME")
    search_index_name  = os.getenv("SEARCH_INDEX_NAME")
    search_api_version = os.getenv("SEARCH_API_VERSION")

    try:
        # 1) Connect to your AI Foundry project and get an AzureOpenAI client
        proj_cred = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
        project = AIProjectClient.from_connection_string(
            conn_str=project_conn_str,
            credential=proj_cred
        )
        oaai_client = project.inference.get_azure_openai_client(
            api_version=openai_api_version,
            connection_name=connection_name
        )

        # 2) Create an Azure Cognitive Search client
        search_endpoint = f"https://{search_service}.search.windows.net"
        search_cred = proj_cred  # same credential can be used
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=search_index_name,
            credential=search_cred,
            api_version=search_api_version
        )

        # 3) Run a simple keyword search over the "content" field
        results = await search_client.search(
            search_text=question,
            search_fields=["content"],
            select=["content", "title"],
            top=5  # pull top 5 matches
        )

        # 4) Build a mini prompt by concatenating the top documents
        docs = []
        async for doc in results:
            snippet = doc.get("content", "").strip()
            title   = doc.get("title", "").strip()
            docs.append(f"Title: {title}\n{snippet}\n")

        context = "\n---\n".join(docs)
        rag_prompt = (
            "You are a helpful assistant. Use the following context from documents to answer the question.\n\n"
            f"{context}\n\n"
            f"Question: {question}\n"
            "Answer:"
        )

        # 5) Send the prompt to the Azure OpenAI model with streaming
        def event_stream():
            stream = oaai_client.chat.completions.create(
                model=deployment_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user",   "content": rag_prompt}
                ],
                stream=True
            )
            for chunk in stream:
                # skip any chunk without choices
                if not getattr(chunk, "choices", None):
                    continue

                choice = chunk.choices[0]
                # get the .content attribute (may be None)
                delta = getattr(choice.delta, "content", None)
                if delta:
                    yield f"{delta}\n\n"


        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logging.exception("Error processing /orcstream")
        raise HTTPException(status_code=500, detail=str(e))
