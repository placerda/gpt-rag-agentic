# Enterprise RAG Agentic Orchestrator

Part of [GPT‑RAG](https://aka.ms/gpt-rag)

## Table of Contents

1. [Concepts](#concepts)  
   1.1 [How the Orchestrator Works](#how-the-orchestrator-works)  
   1.2 [Agent Strategies](#agent-strategies)  
   1.3 [Customization & Extensibility](#customization--extensibility)  
2. [Deployment (Under Review)](#deployment-under-review)  
3. [Evaluation](#evaluation)  
4. [Contributing](#contributing)  
5. [Trademarks](#trademarks)

---

## Concepts

### How the Orchestrator Works

The **GPT‑RAG Agentic Orchestrator** leverages the **Semantic Kernel Agent Framework** instead of AutoGen. At its core, it uses:

- **AgentGroupChat** to manage a multi‑turn, multi‑agent conversation.  
- **ChatCompletionAgent** instances (e.g., a main assistant and a closure agent).  
- **KernelFunctionSelectionStrategy** for turn‑taking rules.  
- **KernelFunctionTerminationStrategy** to decide when to end the chat.  

Each incoming user message is fed into the `AgentGroupChat`, which applies your predefined selection and termination functions to drive the flow and produce a streaming response.

### Agent Strategies

We still use a factory pattern to instantiate strategy classes that subclass `BaseAgentStrategy`:

- **classic_rag**: Retrieval‑Augmented Generation via vector search + LLM.  
- **multimodal_rag**: Combines text and image retrieval.  
- **nl2sql** / **nl2sql_fewshot**: Translates NL into SQL (standard or few‑shot).  
- **chat_with_fabric**: Queries Microsoft Fabric (Lakehouse/semantic models).  

Each strategy’s `create_agents(...)` method wires up its own Kernel, skills (plugins), prompts, and tools.

### Customization & Extensibility

To add your own strategy:

1. **Subclass** `BaseAgentStrategy` and implement `async create_agents(...)`.  
2. **Register** it in `AgentStrategyFactory.get_strategy(...)`.  
3. Set your environment variable `ORCHESTRATION_STRATEGY` to your new enum value.

---

## Deployment (Under Review)

> **Note:** We’re migrating from Azure Function Apps to Container Apps. 

---

## Evaluation

See [docs/EVALUATION.md](docs/EVALUATION.md) for load tests, accuracy checks, and performance benchmarks.

---

## Contributing

Please follow our [CONTRIBUTING guidelines](https://github.com/Azure/GPT-RAG/blob/main/CONTRIBUTING.md).

---

## Trademarks

This project may contain trademarks. Follow [Microsoft's Trademark Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general) for proper use.
