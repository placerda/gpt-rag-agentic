# evaluate.py

import os
from pathlib import Path
from pprint import pprint

import pandas as pd
from fastapi.testclient import TestClient
from azure.identity import (
    ChainedTokenCredential,
    ManagedIdentityCredential,
    AzureCliCredential,
    DefaultAzureCredential
)
from azure.appconfiguration import AzureAppConfigurationClient
from azure.ai.projects import AIProjectClient
from azure.ai.evaluation import evaluate, SimilarityEvaluator

# 1) Bring in your FastAPI app
from main import app  

# 2) Load Azure App Configuration (label="orchestrator") into env
cred = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
cfg_endpoint = os.getenv("APP_CONFIG_ENDPOINT")
if not cfg_endpoint:
    raise EnvironmentError("APP_CONFIG_ENDPOINT must be set")
cfg_client = AzureAppConfigurationClient(base_url=cfg_endpoint, credential=cred)
for kv in cfg_client.list_configuration_settings(label_filter="orchestrator"):
    os.environ[kv.key] = kv.value

# 3) Mount TestClient
client = TestClient(app)

# 4) Prepare your AI Project client and SimilarityEvaluator
project = AIProjectClient.from_connection_string(
    conn_str=os.environ["AI_FOUNDRY_PROJECT_CONNECTION_STRING"],
    credential=DefaultAzureCredential()
)
connection = project.connections.get(
    connection_name=os.environ.get("OPENAI_CONNECTION_NAME", "openai-apim-conn"),
    include_credentials=True
)
evaluator_model = {
    "azure_endpoint": connection.endpoint_url,
    "azure_deployment": os.environ["OPENAI_CHAT_DEPLOYMENT"],
    "api_version": os.environ.get("OPENAI_API_VERSION", "2024-06-01"),
    "api_key": connection.key,
}
similarity = SimilarityEvaluator(evaluator_model)

# 5) Wrapper that calls /orcstream and returns the full text
def evaluate_chat_with_contoso(query: str):
    resp = client.post("/orcstream", json={"question": query})
    # TestClient buffers until the stream ends, then .text contains all chunks
    return {"response": resp.text}

# 6) Run evaluate(...) when executed as a script
if __name__ == "__main__":
    # multiprocessing fork workaround
    import multiprocessing, contextlib
    with contextlib.suppress(RuntimeError):
        multiprocessing.set_start_method("spawn", force=True)

    result = evaluate(
        data="dataset/chat_eval_data.jsonl",
        target=evaluate_chat_with_contoso,
        evaluation_name="evaluate_contoso_similarity",
        evaluators={"similarity": similarity},
        evaluator_config={
            "similarity": {
                "column_mapping": {
                    "query":        "${data.query}",
                    "response":     "${target.response}",
                    "ground_truth":"${data.truth}"
                }
            }
        },        
        azure_ai_project=project.scope,
        output_path="evaluation/evaluation-results.json",
    )

    # show results
    tabular = pd.DataFrame(result["rows"])
    pprint("-----Summarized Metrics-----")
    pprint(result["metrics"])
    pprint("-----Tabular Result-----")
    pprint(tabular)
    pprint(f"View evaluation results in AI Studio: {result['studio_url']}")
