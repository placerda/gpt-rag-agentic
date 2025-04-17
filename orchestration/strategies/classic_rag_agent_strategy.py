# orchestration/strategies/classic_rag_agent_strategy.py

from typing import Annotated
import logging
from semantic_kernel import Kernel
from semantic_kernel.agents import AgentGroupChat, ChatCompletionAgent
from semantic_kernel.agents.strategies import (
    KernelFunctionSelectionStrategy,
    KernelFunctionTerminationStrategy
)
from semantic_kernel.functions import KernelFunctionFromPrompt
from semantic_kernel.contents import ChatHistoryTruncationReducer

import tools.ragindex.vector_index_retrieval as ragindex_plugin
import tools.common.datetools as common_plugin
from tools.ragindex.types import VectorIndexRetrievalResult

from .base_agent_strategy import BaseAgentStrategy
from ..constants import Strategy

class ClassicRAGAgentStrategy(BaseAgentStrategy):

    def __init__(self):
        super().__init__()
        self.strategy_type = Strategy.CLASSIC_RAG
        # how many max turns before we force-stop
        self.max_rounds = int(self.max_rounds)

    async def create_agents(
        self,
        history,
        client_principal=None,
        access_token=None,
        output_mode=None,
        output_format=None
    ):
        # 1) Build a fresh Kernel and register your SK “tools” as plugins
        kernel = Kernel()
        kernel.register_skill("ragindex", ragindex_plugin)
        kernel.register_skill("common", common_plugin)

        # 2) Wrap your vector retrieval function
        async def vector_index_retrieve_wrapper(
            input: Annotated[str, "query"]
        ) -> VectorIndexRetrievalResult:
            sec = self._generate_security_ids(client_principal)
            return await kernel.skills["ragindex"].vector_index_retrieve(input, sec)

        # 3) Read your assistant prompt
        shared_context = await self._get_model_context(history)
        assistant_instructions = await self._read_prompt("main_assistant")

        # 4) Create the two agents: main assistant and chat-closure
        main_agent = ChatCompletionAgent(
            kernel=kernel,
            deployment_name=self.chat_deployment,
            model=self.model,
            instructions=assistant_instructions,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=None
        )
        main_agent.tools = [
            vector_index_retrieve_wrapper,
            kernel.skills["common"].get_today_date,
            kernel.skills["common"].get_time
        ]
        main_agent.model_context = shared_context

        closure_instructions = await self._read_prompt("chat_closure_json")
        closure_agent = ChatCompletionAgent(
            kernel=kernel,
            deployment_name=self.chat_deployment,
            model=self.model,
            instructions=closure_instructions,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=None
        )

        # 5) Define a KernelFunction to select the next speaker
        selection_prompt = """
Given the last message in this group chat, reply EXACTLY with either "main_assistant" or "chat_closure".
- If it's user input or from main_assistant without TERMINATE, pick main_assistant.
- If main_assistant ended with the TERMINATE keyword, pick chat_closure.
LAST_MESSAGE:
{{$history}}
"""
        select_fn = KernelFunctionFromPrompt(
            function_name="select_agent",
            prompt=selection_prompt
        )

        # 6) Define a KernelFunction to decide when we're done
        termination_prompt = """
Have we reached the end of the conversation? 
Reply "yes" if the last assistant message ends with TERMINATE; otherwise "no".
LAST_MESSAGE:
{{$history}}
"""
        term_fn = KernelFunctionFromPrompt(
            function_name="should_terminate",
            prompt=termination_prompt
        )

        # 7) Build the AgentGroupChat
        group_chat = AgentGroupChat(
            agents=[main_agent, closure_agent],
            selection_strategy=KernelFunctionSelectionStrategy(
                initial_agent=main_agent,
                function=select_fn,
                kernel=kernel,
                result_parser=lambda r: r.value[0].strip()
            ),
            termination_strategy=KernelFunctionTerminationStrategy(
                agents=[closure_agent],
                function=term_fn,
                kernel=kernel,
                result_parser=lambda r: r.value[0].lower() == "yes",
                maximum_iterations=self.max_rounds
            ),
            history_reducer=ChatHistoryTruncationReducer(target_count=self.context_buffer_size)
        )

        # 8) Expose the group chat as your single “agent”
        self.agents = [group_chat]  

        return {
            "model_client": group_chat,
            "agents": self.agents,
            "terminate_message": self.terminate_message,
            "termination_condition": self._get_termination_condition(),
            "selector_func": None   # handled by AgentGroupChat now
        }

    async def invoke_agent_stream(self, agent, task: str):
        # If it’s an AgentGroupChat, stream directly from it.
        if isinstance(agent, AgentGroupChat):
            async for msg in agent.invoke_stream(messages=task):
                yield msg.content
        else:
            # fallback to older ChatCompletionAgent
            async for chunk in agent.invoke_stream(messages=task):
                yield getattr(chunk, "text", str(chunk))
