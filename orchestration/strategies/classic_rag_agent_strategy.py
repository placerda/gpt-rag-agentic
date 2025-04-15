from typing import Annotated
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.openai import ChatCompletionAgent

# Import our newly converted Semantic Kernel plugins
import tools.ragindex.vector_index_retrieval as ragindex_plugin
import tools.common.datetools as common_plugin

from tools.ragindex.types import VectorIndexRetrievalResult
from .base_agent_strategy import BaseAgentStrategy
from ..constants import Strategy

class ClassicRAGAgentStrategy(BaseAgentStrategy):

    def __init__(self):
        super().__init__()
        self.strategy_type = Strategy.CLASSIC_RAG

    async def create_agents(self, history, client_principal=None, access_token=None, output_mode=None, output_format=None):
        """
        Creates and configures the main assistant and chat closure agents using Semantic Kernel plugins.
        This strategy sets up its own Kernel instance, registers only the needed skills, and uses
        the SK functions as tools.
        """
        # Create a Kernel instance for the strategy.
        kernel = Kernel()
        # Register only the necessary plugins.
        kernel.register_skill("ragindex", ragindex_plugin)
        kernel.register_skill("common", common_plugin)

        # Build shared conversation context.
        shared_context = await self._get_model_context(history)

        # Define a wrapper for vector_index_retrieve that calls the SK plugin function.
        async def vector_index_retrieve_wrapper(
            input: Annotated[str, "An optimized query string based on the user's ask and conversation history"]
        ) -> VectorIndexRetrievalResult:
            security_ids = self._generate_security_ids(client_principal)
            # Call the SK function from the registered ragindex skill.
            return await kernel.skills["ragindex"].vector_index_retrieve(input, security_ids)

        # Get additional tools from the 'common' plugin.
        get_today_date_tool = kernel.skills["common"].get_today_date  # Already decorated as an SK function.
        get_time_tool = kernel.skills["common"].get_time

        # Retrieve the main assistant prompt.
        assistant_prompt = await self._read_prompt("main_assistant")

        # Create the main assistant agent using our configured kernel.
        # Here we directly set the instructions to the prompt.
        main_assistant = ChatCompletionAgent(
            kernel=kernel,
            deployment_name=self.chat_deployment,
            model=self.model,
            instructions=assistant_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=None  # Optionally, use ChatGroupResponse if needed.
        )
        # Attach the SK tool wrappers as a tools list.
        main_assistant.tools = [vector_index_retrieve_wrapper, get_today_date_tool, get_time_tool]
        main_assistant.model_context = shared_context

        # Create the chat closure agent (using, for example, a JSON prompt for closure).
        # (You can adjust the prompt name and response format as desired.)
        chat_closure_prompt = await self._read_prompt("chat_closure_json")
        chat_closure = ChatCompletionAgent(
            kernel=kernel,
            deployment_name=self.chat_deployment,
            model=self.model,
            instructions=chat_closure_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=None
        )

        # Define a custom selector function that picks the next agent based on the source of the last message.
        def custom_selector_func(messages):
            last_msg = messages[-1]
            if getattr(last_msg, "source", None) == "user":
                return "main_assistant"
            if getattr(last_msg, "source", None) == "main_assistant":
                if hasattr(last_msg, "text") and last_msg.text.strip().endswith(self.terminate_message):
                    return "chat_closure"
                else:
                    return "main_assistant"
            return None

        self.selector_func = custom_selector_func

        # Register agents by name; here, we use the names set within the agent objects.
        self.agents = [main_assistant, chat_closure]

        # Return the configuration dictionary (API remains unchanged).
        return self._get_agents_configuration()
