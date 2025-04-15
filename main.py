# app.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio
import logging
from orchestration import RequestResponseOrchestrator, StreamingOrchestrator, OrchestratorConfig

# Initialize FastAPI app
main = FastAPI()
config = OrchestratorConfig()  # This reads environment variables to set up the orchestration strategy

# Endpoint for the standard request-response scenario
@main.post("/orc")
async def orc_endpoint(request: Request):
    data = await request.json()
    conversation_id = data.get("conversation_id")
    question = data.get("question")
    client_principal = {
        "id": data.get("client_principal_id", "00000000-0000-0000-0000-000000000000"),
        "name": data.get("client_principal_name", "anonymous"),
        "group_names": data.get("client_group_names", "")
    }
    access_token = data.get("access_token")
    
    if not question:
        raise HTTPException(status_code=400, detail="No question found in JSON input.")
    
    try:
        orchestrator = RequestResponseOrchestrator(conversation_id, config, client_principal, access_token)
        result = await orchestrator.answer(question)
    except Exception as e:
        logging.exception("Error while processing the /orc endpoint")
        raise HTTPException(status_code=500, detail=str(e))
    
    return JSONResponse(content=result)

# Endpoint for the streaming scenario
@main.post("/orcstream")
async def orcstream_endpoint(request: Request):
    data = await request.json()
    conversation_id = data.get("conversation_id")
    question = data.get("question")
    optimize_for_audio = data.get("optimize_for_audio", False)
    client_principal = {
        "id": data.get("client_principal_id", "00000000-0000-0000-0000-000000000000"),
        "name": data.get("client_principal_name", "anonymous"),
        "group_names": data.get("client_group_names", "")
    }
    access_token = data.get("access_token")
    
    if not question:
        raise HTTPException(status_code=400, detail="No question found in JSON input.")
    
    try:
        orchestrator = StreamingOrchestrator(conversation_id, config, client_principal, access_token)
        orchestrator.set_optimize_for_audio(optimize_for_audio)

        async def stream_generator():
            async for chunk in orchestrator.answer(question):
                yield chunk

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    except Exception as e:
        logging.exception("Error while processing the /orcstream endpoint")
        raise HTTPException(status_code=500, detail=str(e))
