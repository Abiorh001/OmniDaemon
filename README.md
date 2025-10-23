
# 🌐 OmniDaemon

### **Universal Event-Driven Runtime for AI Agents**

> **Run any AI agent. Any framework. One event-driven control plane.**

OmniDaemon is a **lightweight, production-ready runtime** for **autonomous, background AI agents** — designed for **event-driven, asynchronous workflows**, not chatbots or request-response APIs.

Agents run continuously in the background, triggered by **events** (e.g., `document.uploaded`, `inventory.low`), with built-in support for **retries, dead-letter queues, observability, and lifecycle control**.

✅ **Framework-agnostic**: Use LangChain, AutoGen, LlamaIndex, CrewAI, custom code, or our own `OmniCoreAgent` — **no vendor lock-in**.  
✅ **Pluggable infrastructure**: Redis, Kafka, NATS, RabbitMQ for messaging; Redis, PostgreSQL, MongoDB for results.  
✅ **Full observability**: CLI + HTTP API + DLQ monitoring + real-time metrics.  
✅ **Developer-first**: Decorator-based registration, rich CLI, auto `task_id`, webhook callbacks.

---

## 🌍 Vision

**OmniDaemon** is to **AI agents** what **Kubernetes** is to **containers** — a universal runtime that makes intelligent systems autonomous, observable, and scalable.

Our vision is to build the **foundational layer for distributed AI infrastructure** — starting from a simple belief:

> that AI agents shouldn’t just execute prompts, but **live, listen, and react** like real systems.

Born from the need to bridge **intelligence and infrastructure**, OmniDaemon transforms AI from static reasoning engines into **event-driven, self-operating entities** that integrate seamlessly across clouds, data streams, and enterprise environments.

This is how we move AI from experiments to **living, autonomous infrastructure.**

---

## 🚀 Quick Start

### 1. Define an agent
```python
# agents.py
from omnidaemon import OmniDaemonSDK

sdk = OmniDaemonSDK()

@sdk.agent("greet.user")
async def greeter(payload):
    return {"reply": f"Hello, {payload['name']}!"}

if __name__ == "__main__":
    sdk.run()
```

### 2. Run it (with API enabled)
```bash
OMNIDAEMON_API_ENABLED=true python agents.py
```

### 3. Control it from CLI
```bash
# Publish a background task
omni task publish greet.user '{"name":"Alice"}'

# List running agents
omni agent list

# Monitor Redis Streams
omni bus watch

# View metrics
omni metrics
```

---

## 🧠 Core Concepts

### 🔁 **Event-Driven, Not Request-Driven**
- Agents **subscribe to topics**, not HTTP endpoints
- Tasks are **published as events**, not API calls
- Execution is **asynchronous and decoupled**

### 🧩 **Framework Agnostic**
Your agent can be:
- `OmniCoreAgent`
- Google ADK
- Pydantic AI
- A LangChain chain
- An AutoGen group chat
- A plain Python function
- A custom PyTorch pipeline


OmniDaemon only requires a **callable** that accepts a `Dict` and returns a result.

### ⚙️ **Pluggable Architecture**

#### Event Bus (Messaging)
| Backend | Status |
|--------|--------|
| Redis Pub-Sub | ✅ Local-Development |
| Redis Streams | ✅ Production-ready |
| Kafka | 🚧 Coming soon |
| NATS JetStream | 🚧 Coming soon |
| RabbitMQ | 🚧 Coming soon |

#### Result Store (Persistence)
| Backend | Status |
|--------|--------|
| Redis | ✅ |
| PostgreSQL | 🚧 Coming soon |
| MongoDB | 🚧 Coming soon |

Configure via environment variables:
```env
EVENT_BUS_TYPE=redis_stream
RESULT_STORE_TYPE=redis
OMNIDAEMON_API_ENABLED=true
OMNIDAEMON_API_PORT=8765
OMNIDAEMON_API_URL=http://localhost:8765
```

---

## 🛠️ Developer Experience

### 🔹 Quick Start (Decorator Style)

For simple or prototype setups, you can define agents using decorators and call `sdk.run()`:

```python
from src.omnidaemon.sdk import OmniDaemonSDK

sdk = OmniDaemonSDK()

@sdk.agent("recipe.tasks", name="RecipeBot", tools=["search"])
async def recipe_agent(payload):
    return await my_agent.run(payload)

sdk.run()  # Starts agent + built-in HTTP API
```

This approach is ideal for **fast iteration and local testing** — OmniDaemon automatically discovers and runs the agent.

---

### 🔹 Advanced Setup (Production / Multi-Agent Mode)

For more complex or enterprise systems — where you may want multiple agents, background tasks, or API integration — use the `.start()` method instead of `.run()`:

```python
import asyncio
from src.omnidaemon.sdk import OmniDaemonSDK
from src.omnidaemon.runners import OmniAgentRunner
from src.omnidaemon.api import start_api_server
from loguru import logger
from decouple import config

sdk = OmniDaemonSDK()

document_runner = OmniAgentRunner()
recipe_runner = OmniAgentRunner()

async def document_agent(message):
    await document_runner.initialize()
    result = await document_runner.handle_chat(message.get("content"))
    return {"status": "success", "data": result}

async def recipe_agent(message):
    await recipe_runner.initialize()
    result = await recipe_runner.handle_chat(message.get("content"))
    return {"status": "success", "data": result}

async def main():
    # Register multiple agents for different topics
    await sdk.register_agent("document.conversion.tasks", callback=document_agent)
    await sdk.register_agent("recipe.tasks", callback=recipe_agent)

    # Start OmniDaemon core
    await sdk.start()

    # Optionally launch REST API
    if config("OMNIDAEMON_API_ENABLED", default=False, cast=bool):
        port = config("OMNIDAEMON_API_PORT", default=8765, cast=int)
        asyncio.create_task(start_api_server(sdk, port=port))
        logger.info(f"OmniDaemon API running on http://127.0.0.1:{port}")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await sdk.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

> ✅ Use `.start()` instead of `.run()` when you need to:
>
> * Run **multiple agents** at once
> * Start **FastAPI or custom HTTP APIs**
> * Integrate with **Redis, Kafka, or RabbitMQ** event buses
> * Manage **graceful shutdowns** and **background schedulers**

---

## 🚀 Publishing Tasks

You can publish tasks to any agent topic using the SDK’s built-in `publish_task()` method.
OmniDaemon supports multiple message buses (Redis, Kafka, RabbitMQ, NATS, etc.), and results can be retrieved from the configured `ResultStore`.

```python
import asyncio
from src.omnidaemon.sdk import OmniDaemonSDK
from src.omnidaemon.result_store import RedisResultStore

# Connect to Redis (or any supported store)
sdk = OmniDaemonSDK(result_store=RedisResultStore(redi_url=config("REDIS_URL", default="redis://localhost")))

async def publish_tasks():
    tasks = [
        (
            "document.conversion.tasks",
            {
                "content": "what can you do for me",
                "webhook": "http://localhost:8004/document_conversion_result",
            },
        ),
        (
            "recipe.tasks",
            {
                "content": "what can I cook with rice and apple",
            },
        ),
    ]

    for topic, payload in tasks:
        # Publish task to topic
        task_id = await sdk.publish_task(topic, payload)
        print(f"📨 Published task {task_id} → {topic}")

        # Optionally wait for result
        await asyncio.sleep(3)
        result = await sdk.get_result(task_id)
        print(f"✅ Result for {task_id}: {result}")

if __name__ == "__main__":
    asyncio.run(publish_tasks())
```

---

### 🧩 Notes

* `topic` → the event bus channel (e.g., `"recipe.tasks"`) that your agent is subscribed to.
* `payload` → task data sent to the agent (can include text, files, or webhook callbacks).
* `get_result(task_id)` → retrieves the result stored by the agent through your configured `ResultStore`.
* Webhooks are supported for **asynchronous delivery** if your agents publish responses to external endpoints.

---

### 💡 Example Workflow

1. Start your multi-agent runner:

   ```bash
   python agents_runner.py
   ```

2. Publish a task to the bus:

   ```bash
   python publisher.py
   ```

3. Watch as OmniDaemon automatically routes messages to the right agent, runs it, and persists the results.

---




### CLI
```bash
# Agent control
omni agent list
omni agent stop recipe.tasks RecipeBot

# Task management
omni task publish recipe.tasks '{"query":"cake"}'
omni task result <task_id>

# Infrastructure monitoring (Redis-only)
omni bus list
omni bus dlq recipe.tasks
omni bus watch

# Observability
omni health
omni metrics
```

### HTTP API (for cross-process control)
```bash
curl http://localhost:8765/agents
curl -X POST http://localhost:8765/agents/recipe.tasks/RecipeBot/stop
curl http://localhost:8765/tasks/<task_id>
curl http://localhost:8765/metrics
```

All output uses **colorful tables, panels, and ASCII art**:

---

## 📡 HTTP API Reference

All endpoints assume:  
- **URL**: `http://localhost:8765`  
- **Auth**: None (localhost-only by default)  
- **Format**: JSON

| Endpoint | Method | Description |
|--------|--------|-------------|
| `/agents` | `GET` | List all agents |
| `/agents/{topic}/{name}` | `GET` | Get agent details |
| `/agents/{topic}/{name}/start` | `POST` | Start an agent |
| `/agents/{topic}/{name}/stop` | `POST` | Stop an agent |
| `/agents/start` | `POST` | Start all agents |
| `/agents/stop` | `POST` | Stop all agents |
| `/tasks` | `POST` | Publish a new task |
| `/tasks/{task_id}` | `GET` | Retrieve task result |
| `/health` | `GET` | System health check |
| `/metrics` | `GET` | Real-time agent metrics |

> 💡 Full `curl` examples in the [API Guide](#-http-api-reference) below.

---

## 📊 Metrics

OmniDaemon tracks **per-agent, per-topic execution metrics**:

| Metric | Description |
|-------|------------|
| `tasks_received` | Total tasks received |
| `tasks_processed` | Successfully completed tasks |
| `tasks_failed` | Tasks that raised exceptions |
| `tasks_skipped` | Tasks skipped due to `status=stopped` |
| `avg_processing_time_sec` | Average processing time |

View via:
```bash
omni metrics
```

Or:
```bash
curl http://localhost:8765/metrics
```

---

## 🏗️ Architecture

![OmniDaemon Architecture](https://www.plantuml.com/plantuml/svg/bLLDR-Cs4BtxLx0v50uQHvUU2XHOVsInQP9TnNAswCcWf8b4c2Ar7DAxHj7_Neue4PQjo_faKdnlXZDl7Z-WvSQwHiv-4QgGhWHMMzlY7qbY-FVxIjZQvGx155fPKFQ-q4tIIgu8iq1RIf4dwzyNAMszlJmd3KSBnc_jrnx1XG9ptnB_B0M3MkqVVjWv4TwncmqSGUeM34kOtmQZk6JPoHCqD_xp6mAozVCZquOXg1APvNZ0czlPB1pQhxHJ9JUdkMwKA3aqMddS5x_OT8k1x9RzEsF-5rEQOtcuEBbvefZfoTPQqRyjL8AkWenNe2pUiTRbKc0DCOyBJkEKwkwruWXB0csxdJ5lvd8iZCY9HZCu-cCiTvxUmuTOLzIy5HxwQRTBsJ9zP1cOO-3zoD7w7VhxyAFL23q5etuPBTbHSBPzo7PNbE-yiDgS24Wvh1n-33lZTDS6kFMiCL6MdvWzjS3c1ag1oO6_7tYYkCN4y3mNjlbsUrqQG2SjUdgWqdQhZ5RiKLamFXSOXqsbgogUIs01obemIFrG1Lon5vAgGneWkH1yTo9L_SQsegXxAPc5Zo9KrIdgNPjOeL-Pxx_moVYFdlg_sMmMgKcjuPvxVtLAdVwpp1hW3HBp2o3o2jZAw4FVQfSdlidikx0rspo_tb4aT0qOLXdjMkhkE41NmZx0ikL53Uo9jgRvFucgNjZQKrLrwspV6UnIybUuOgVMzEIVbxkC_GKsv3zDlvRQbGiF4aTWJVTvYZNqUgXAjtXvdMPSlhocYvmZbCmdRGFRT96ZGcX5s2SuBRvowO1rSXaaFwYYyCMQogwj8bMgqLO6ijVdCDMIMw79Q3Ohsl2bS8LrFlp0IK1UmHMdLqcb8-qBhGB5HXUk0MK7Hj-_XYya85vJpdm2lVq5rMvfwhsfDboLI71IyEtPiU1KQoub3Wwq9_-Ptzxqbf1KstGzS7V7Xzcc-tvpWFPiVZkh-FhmURTVlMNxtJ_fGnykWgBUu_Xt8F7UpVsVuNFGsoKqAdaQsds-n0pwd8RGrql4I7iJcC67pceolbKwSdA2aaqEFXZ2HJkFm2lpjheL1Kx0H_ZGm6LmPIvbpej31tfKYzRe0l0guiWjCtw4GKans9c53k1pq7YQtZ3Mfz3gNLGazobOM_qyPZmMqx2BYlJF_z-GrreVs5otOIIZebdw9Tk5OC7SUIlY42J3Uvnqp_20wOzt9qCWGWIF7nv5jDowwzh7C6EdvoNsjkhNPEI3VyTtO5uA0uMzepTbePKyqSlt0LJf6la_)


---

## 📦 Installation

```bash
pip install omnidaemon
```

```bash
uv add omnidaemon
```

Or from source:
```bash
git https://github.com/Abiorh001/OmniDaemon
cd OmniDaemon
pip install -e .
```

---

## 🌍 Philosophy

> **“Your agents. Your rules. One runtime.”**

OmniDaemon believes the future of AI is **multi-agent, multi-framework, and event-driven**. We provide the **universal runtime** — you bring the agents.

No lock-in. No opinions. Just pure, scalable, observable agent execution.

---

## 📬 What’s Next?

- [ ] RabbitMQ event bus implementation
- [ ] Kafka event bus implementation
- [ ] NATS JetStream support
- [ ] Prometheus metrics exporter
- [ ] Web UI dashboard
- [ ] Kubernetes operator for scaling