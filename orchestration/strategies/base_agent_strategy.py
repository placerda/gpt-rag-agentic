import logging
import os
import re

from pydantic import BaseModel
from ..constants import OutputFormat, OutputMode

# Import Semantic Kernel components
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.openai import ChatCompletionAgent

# Agent response types remain unchanged.
class ChatGroupResponse(BaseModel):
    answer: str
    reasoning: str

class BaseAgentStrategy:
    def __init__(self):
        # Configuration parameters from environment variables.
        self.aoai_resource = os.environ.get('AZURE_OPENAI_RESOURCE', 'openai')
        self.chat_deployment = os.environ.get('AZURE_OPENAI_CHATGPT_DEPLOYMENT', 'chat')
        self.model = os.environ.get('AZURE_OPENAI_CHATGPT_MODEL', 'gpt-4o')
        self.api_version = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-10-21')
        self.max_tokens = int(os.environ.get('AZURE_OPENAI_MAX_TOKENS', 1000))
        self.temperature = float(os.environ.get('AZURE_OPENAI_TEMPERATURE', 0.7))
        
        # Agent configuration – used by orchestrators.
        self.agents = []
        self.terminate_message = "TERMINATE"
        self.max_rounds = int(os.getenv('MAX_ROUNDS', 8))
        self.selector_func = None
        self.context_buffer_size = int(os.getenv('CONTEXT_BUFFER_SIZE', 30))
        self.text_only = False 
        self.optimize_for_audio = False

    async def create_agents(self, history, client_principal=None, access_token=None, text_only=False, optimize_for_audio=False): 
        """
        Create agent instances for the strategy.
        Must be overridden by subclasses.
        """
        raise NotImplementedError("This method should be overridden in subclasses.")

    def _get_agents_configuration(self):
        """
        Retrieve and return the configuration dictionary required by the orchestrators.
        This includes the model client, agents list, termination details, and the selector function.
        """
        return {
            "model_client": self._get_model_client(),
            "agents": self.agents,
            "terminate_message": self._get_terminate_message(),            
            "termination_condition": self._get_termination_condition(),
            "selector_func": self.selector_func
        }

    def _get_terminate_message(self):
        return self.terminate_message

    def _get_model_client(self, response_format=None):
        """
        Set up a Semantic Kernel language model client.
        This method creates a new Kernel instance and returns a ChatCompletionAgent.
        """
        kernel = Kernel()
        agent = ChatCompletionAgent(
            kernel=kernel,
            deployment_name=self.chat_deployment,
            model=self.model,
            # "instructions" will be set later, such as via the prompt.
            instructions="",
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=response_format
        )
        logging.info("Semantic Kernel ChatCompletionAgent instantiated successfully.")
        return agent

    def _get_termination_condition(self):
        """
        Define a termination condition for agent interactions.
        This is a simple lambda that checks whether the response ends with the terminate message.
        """
        return lambda response: response.strip().endswith(self.terminate_message)

    async def _summarize_conversation(self, history: list) -> str:
        """
        Summarize the conversation history.
        In this simplified example, join the 'content' field of each message.
        """
        if history:
            conversation_summary = "\n".join(item.get("content", "") for item in history)
        else:
            conversation_summary = "The conversation just started."
        logging.info(f"[base_agent_strategy] Conversation summary: {conversation_summary[:200]}")
        return conversation_summary

    def _generate_security_ids(self, client_principal):
        """
        Generate a security identifier string based on the client principal.
        """
        security_ids = 'anonymous'
        if client_principal is not None:
            group_names = client_principal.get('group_names', '')
            security_ids = f"{client_principal.get('id', 'unknown')}" + (f",{group_names}" if group_names else "")
        return security_ids

    async def _read_prompt(self, prompt_name, placeholders=None):
        """
        Load and process a prompt file with optional placeholder substitutions.
        The prompt file is determined by the current strategy's type.
        """
        prompt_file_path = os.path.join(self._prompt_dir(), f"{prompt_name}.txt")
        if not os.path.exists(prompt_file_path):
            logging.error(f"[base_agent_strategy] Prompt file '{prompt_name}' not found: {prompt_file_path}.")
            raise FileNotFoundError(f"Prompt file '{prompt_name}' not found.")
        logging.info(f"[base_agent_strategy] Using prompt file path: {prompt_file_path}")
        with open(prompt_file_path, "r") as f:
            prompt = f.read().strip()
        if placeholders:
            for key, value in placeholders.items():
                prompt = prompt.replace(f"{{{{{key}}}}}", value)
        pattern = r"\{\{([^}]+)\}\}"
        matches = re.findall(pattern, prompt)
        for placeholder_name in set(matches):
            if placeholders and placeholder_name in placeholders:
                continue
            common_file_path = os.path.join("prompts", "common", f"{placeholder_name}.txt")
            if os.path.exists(common_file_path):
                with open(common_file_path, "r") as pf:
                    placeholder_content = pf.read().strip()
                    prompt = prompt.replace(f"{{{{{placeholder_name}}}}}", placeholder_content)
            else:
                logging.warning(f"[base_agent_strategy] Placeholder '{{{{{placeholder_name}}}}}' could not be replaced.")
        return prompt

    def _prompt_dir(self):
        """
        Return the prompt directory based on the strategy's type.
        """
        if not hasattr(self, 'strategy_type'):
            raise ValueError("strategy_type is not defined")
        return os.path.join("prompts", self.strategy_type.value)

    async def _get_model_context(self, history):
        """
        Obtain a summary of the conversation history to use as context.
        """
        history_summary = await self._summarize_conversation(history)
        return history_summary

    async def _create_chat_closure_agent(self, output_format, output_mode):
        """
        Create a chat closure agent based on the specified output format and mode.
        This instantiates a separate ChatCompletionAgent using a designated prompt.
        """
        if output_format is None or output_mode is None:
            raise ValueError("Both output_format and output_mode must be specified.")
        if output_format == OutputFormat.TEXT_TTS:
            prompt_name = "chat_closure_tts"
        elif output_format == OutputFormat.JSON:
            prompt_name = "chat_closure_json"
        elif output_format == OutputFormat.TEXT:
            prompt_name = "chat_closure_text"
        instructions = await self._read_prompt(prompt_name)
        closure_agent = ChatCompletionAgent(
            kernel=Kernel(),  # Optionally, reuse an existing Kernel instance.
            deployment_name=self.chat_deployment,
            model=self.model,
            instructions=instructions,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format=None
        )
        return closure_agent

    async def invoke_agent_stream(self, agent, task: str):
        """
        Abstract the streaming invocation of a Semantic Kernel agent.
        This async generator yields text chunks as they arrive from the agent's streaming interface.
        """
        try:
            async for response in agent.invoke_stream(messages=[f"User: {task}"]):
                # Assume the response object has a 'text' attribute.
                yield getattr(response, "text", str(response))
        except Exception as e:
            logging.error(f"Error during streaming invocation: {e}")
            yield f"Error: {e}"
