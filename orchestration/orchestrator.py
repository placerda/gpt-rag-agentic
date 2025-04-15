import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from .constants import Strategy, OutputFormat, OutputMode
from connectors import CosmosDBClient
from .agent_strategy_factory import AgentStrategyFactory

# ---------- Configuration & Dependency Classes ----------

class OrchestratorConfig:
    def __init__(
        self,
        conversation_container: str = None,
        storage_account: str = None,
        orchestration_strategy: Strategy = None,
    ):
        self.conversation_container = conversation_container or os.environ.get('CONVERSATION_CONTAINER', 'conversations')
        self.storage_account = storage_account or os.environ.get('AZURE_STORAGE_ACCOUNT', 'your_storage_account')
        strategy_from_env = os.getenv('ORCHESTRATION_STRATEGY', 'classic_rag').replace('-', '_')
        self.orchestration_strategy = (orchestration_strategy or Strategy(strategy_from_env))


class ConversationManager:
    def __init__(self, cosmosdb_client: CosmosDBClient, config: OrchestratorConfig,
                 client_principal: dict, conversation_id: str):
        self.cosmosdb = cosmosdb_client
        self.config = config
        self.client_principal = client_principal
        self.conversation_id = self._use_or_create_conversation_id(conversation_id)
        self.short_id = self.conversation_id[:8]

    def _use_or_create_conversation_id(self, conversation_id: str) -> str:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            logging.info(f"[orchestrator] Creating new conversation_id: {conversation_id}")
        return conversation_id

    async def get_or_create_conversation(self) -> dict:
        conversation = await self.cosmosdb.get_document(self.config.conversation_container, self.conversation_id)
        if not conversation:
            new_conversation = {
                "id": self.conversation_id,
                "start_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": self.client_principal.get("id", "unknown") if self.client_principal else "unknown",
                "user_name": self.client_principal.get("name", "anonymous") if self.client_principal else "anonymous",
                "conversation_id": self.conversation_id,
                "history": []  # initialize an empty chat log
            }
            conversation = await self.cosmosdb.create_document(self.config.conversation_container, self.conversation_id, new_conversation)
            logging.info(f"[orchestrator] {self.short_id} Created new conversation.")
        else:
            logging.info(f"[orchestrator] {self.short_id} Retrieved existing conversation.")
        return conversation

    async def update_conversation(self, conversation: dict, ask: str, answer: str):
        logging.info(f"[orchestrator] {self.short_id} Updating conversation.")
        history = conversation.get("history", [])
        history.extend([
            {"speaker": "user", "content": ask},
            {"speaker": "assistant", "content": answer}
        ])
        simplified_conversation = {
            "id": self.conversation_id,
            "start_date": conversation.get("start_date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "user_id": self.client_principal.get("id", "unknown") if self.client_principal else "unknown",
            "user_name": self.client_principal.get("name", "anonymous") if self.client_principal else "anonymous",
            "conversation_id": self.conversation_id,
            "history": history
        }
        await self.cosmosdb.update_document(self.config.conversation_container, simplified_conversation)
        logging.info(f"[orchestrator] {self.short_id} Finished updating conversation.")


# ---------- Orchestrators ----------

class BaseOrchestrator(ABC):
    def __init__(
        self,
        conversation_id: str,
        config: OrchestratorConfig,
        client_principal: dict = None,
        access_token: str = None,
        agent_strategy=None
    ):
        self.client_principal = client_principal
        self.access_token = access_token
        self.cosmosdb =  CosmosDBClient()
        self.conversation_manager = ConversationManager(self.cosmosdb, config, client_principal, conversation_id)
        self.conversation_id = self.conversation_manager.conversation_id
        self.short_id = self.conversation_id[:8]
        self.config = config

        # Agent strategy is injected if provided; otherwise, use the factory.
        if agent_strategy:
            self.agent_strategy = agent_strategy
        else:
            strategy_key = config.orchestration_strategy
            self.agent_strategy = AgentStrategyFactory.get_strategy(strategy_key)

    @abstractmethod
    async def answer(self, ask: str):
        pass

    @abstractmethod
    async def _create_agents_with_strategy(self, history: list[dict]) -> dict:
        pass

    async def _update_conversation(self, conversation: dict, ask: str, answer: str):
        await self.conversation_manager.update_conversation(conversation, ask, answer)


class RequestResponseOrchestrator(BaseOrchestrator):
    async def answer(self, ask: str) -> dict:
        start_time = time.time()
        conversation = await self.conversation_manager.get_or_create_conversation()
        history = conversation.get("history", [])
        agent_configuration = await self._create_agents_with_strategy(history)
        # For non-streaming response, aggregate text from the streaming invocation.
        # Here we select the first agent from the configuration.
        selected_agent = agent_configuration["agents"][0]
        aggregated_answer = ""
        async for chunk in self.agent_strategy.invoke_agent_stream(selected_agent, ask):
            aggregated_answer += chunk
        # Remove the termination marker if present.
        if aggregated_answer.endswith(agent_configuration['terminate_message']):
            aggregated_answer = aggregated_answer[:-len(agent_configuration['terminate_message'])].strip()
        await self._update_conversation(conversation, ask, aggregated_answer)
        response_time = time.time() - start_time
        logging.info(f"[orchestrator] {self.short_id} Generated response in {response_time:.3f} sec.")
        return {
            "conversation_id": self.conversation_id,
            "answer": aggregated_answer,
            "reasoning": "",  # Reasoning is not extracted in this implementation.
            "thoughts": [],
            "data_points": []
        }

    async def _create_agents_with_strategy(self, history: list[dict]) -> dict:
        logging.info(f"[orchestrator] {self.short_id} Creating agents using {self.agent_strategy.strategy_type} strategy.")
        return await self.agent_strategy.create_agents(history, self.client_principal, self.access_token, OutputMode.REQUEST_RESPONSE, OutputFormat.JSON)


class StreamingOrchestrator(BaseOrchestrator):
    def __init__(
        self,
        conversation_id: str,
        config: OrchestratorConfig,
        client_principal: dict = None,
        access_token: str = None,
        agent_strategy=None
    ):
        super().__init__(conversation_id, config, client_principal, access_token, agent_strategy)
        self.optimize_for_audio = False

    def set_optimize_for_audio(self, optimize_for_audio: bool):
        self.optimize_for_audio = optimize_for_audio

    async def answer(self, ask: str):
        conversation = await self.conversation_manager.get_or_create_conversation()
        history = conversation.get("history", [])
        agent_config = await self._create_agents_with_strategy(history)
        # Select an agent to perform streaming.
        selected_agent = agent_config["agents"][0]
        streamed_conversation_id = False
        final_answer = ""
        try:
            async for chunk in self.agent_strategy.invoke_agent_stream(selected_agent, ask):
                if not streamed_conversation_id:
                    # Yield conversation id in the first chunk.
                    yield f"{conversation['id']} "
                    streamed_conversation_id = True
                yield chunk
                final_answer += chunk
        except Exception as error:
            logging.error(f"Error in streaming response: {error}", exc_info=True)
            error_message = f"\nWe encountered an issue processing your request. Please contact our support team for assistance.\n\nError: {error}"
            yield error_message
            final_answer += error_message
        await self._update_conversation(conversation, ask, final_answer)

    async def _create_agents_with_strategy(self, history: list[dict]) -> dict:
        output_format = OutputFormat.TEXT_TTS if self.optimize_for_audio else OutputFormat.TEXT
        logging.info(f"[orchestrator] {self.short_id} Creating agents using {self.agent_strategy.strategy_type} strategy. In Streaming mode and {output_format} output format.")
        return await self.agent_strategy.create_agents(history, self.client_principal, self.access_token, OutputMode.STREAMING, output_format)
