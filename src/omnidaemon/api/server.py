from fastapi import FastAPI, HTTPException, status
import uvicorn
from typing import Dict, Any

from omnidaemon.sdk import OmniDaemonSDK
from omnidaemon.schemas import AgentConfig, EventEnvelope, PayloadBase


def create_app(sdk: OmniDaemonSDK) -> FastAPI:
    app = FastAPI(
        title="OmniDaemon Control API",
        description="HTTP API to manage agents, tasks, and health of a running OmniDaemon instance.",
        version="0.0.1",
    )

    @app.post(
        "/publish-tasks",
        summary="Publish a new event/task to OmniDaemon",
        response_model=dict,
        response_description="Returns the published task ID and status.",
    )
    async def publish_task(event: EventEnvelope):
        """
        Publish a fully structured event to OmniDaemon.

        This endpoint allows publishing complex task envelopes
        that include correlation IDs, metadata, tenant information,
        and arbitrary payload content.

        Example request body:
        ```json
        {
            "topic": "recipe.tasks",
            "payload": {
                "content": "generate_recipe",
                "webhook": "https://example.com/callback",
                "reply_to": "recipe.responses"
            },
            "tenant_id": "tenant-123",
            "correlation_id": "req-789",
            "source": "web-api"
        }
        ```
        """
        try:
            task_id = await sdk.publish_task(event_envelope=event)
            return {"task_id": task_id, "status": "published"}

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid event: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to publish task: {e}",
            )

    @app.get("/agents")
    async def list_agents():
        """List all registered agents grouped by topic."""
        return sdk.list_agents()

    @app.get("/agents/{topic}/{name}")
    async def get_agent(topic: str, name: str):
        """Get a specific agent by topic and name."""
        agent = await sdk.get_agent(topic=topic, agent_name=name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @app.post("/agents/{topic}/{name}/unsubscribe")
    async def unsubscribe_agent(topic: str, name: str):
        """
        Pause agent processing (unsubscribe).

        This temporarily stops the agent from consuming new messages but keeps:
        - Consumer group intact (messages continue to queue)
        - DLQ preserved (failed messages kept)
        - Agent data in storage

        To resume, simply restart the agent runner.
        """
        success = await sdk.unsubscribe_agent(topic=topic, agent_name=name)
        if not success:
            raise HTTPException(
                status_code=404, detail="Agent not found or not running"
            )
        return {
            "status": "unsubscribed",
            "topic": topic,
            "agent": name,
            "message": "Agent paused. Messages will queue. Restart runner to resume.",
        }

    @app.delete("/agents/{topic}/{name}")
    async def delete_agent(
        topic: str, name: str, delete_group: bool = True, delete_dlq: bool = False
    ):
        """
        Permanently delete an agent.

        Query Parameters:
        - delete_group: Delete consumer group from Redis (default: True)
        - delete_dlq: Also delete the dead-letter queue (default: False)

        This performs a complete cleanup:
        - Stops processing (unsubscribes)
        - Deletes consumer group from Redis (by default)
        - Optionally deletes DLQ
        - Removes agent data from storage
        """
        deleted = await sdk.delete_agent(
            topic=topic,
            agent_name=name,
            delete_group=delete_group,
            delete_dlq=delete_dlq,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Agent not found")

        cleanup_info = {
            "storage_deleted": True,
            "consumer_group_deleted": delete_group,
            "dlq_deleted": delete_dlq,
        }

        return {
            "status": "deleted",
            "topic": topic,
            "agent": name,
            "cleanup": cleanup_info,
        }

    @app.delete("/agents/topic/{topic}")
    async def delete_topic(topic: str):
        """Delete all agents for a topic."""
        count = await sdk.delete_topic(topic=topic)
        return {"status": "deleted", "topic": topic, "agents_deleted": count}

    @app.get("/health")
    async def health():
        """Get runner health and status."""
        return sdk.health()

    @app.get("/tasks/{task_id}")
    async def get_task_result(task_id: str):
        """Get task result by ID."""
        result = await sdk.get_result(task_id)
        if result is None:
            raise HTTPException(
                status_code=404, detail="Task not found or not completed"
            )
        return result

    @app.get("/tasks")
    async def list_results(limit: int = 100):
        """List recent task results."""
        return await sdk.list_results(limit=limit)

    @app.delete("/tasks/{task_id}")
    async def delete_result(task_id: str):
        """Delete a task result."""
        deleted = await sdk.delete_result(task_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Task result not found")
        return {"status": "deleted", "task_id": task_id}

    @app.get("/metrics")
    async def metrics(topic: str = None, limit: int = 1000):
        """Get aggregated metrics from unified storage."""
        return await sdk.metrics(topic=topic, limit=limit)

    @app.get("/storage/health")
    async def storage_health():
        """Get storage backend health information."""
        return await sdk.storage_health()

    @app.post("/config/{key}")
    async def save_config(key: str, value: Dict[str, Any]):
        """Save a configuration value."""
        await sdk.save_config(key, value.get("value"))
        return {"status": "saved", "key": key}

    @app.get("/config/{key}")
    async def get_config(key: str, default: str = None):
        """Get a configuration value."""
        value = await sdk.get_config(key, default=default)
        return {"key": key, "value": value}

    @app.delete("/storage/agents")
    async def clear_agents():
        """
        DELETE ALL agents.

        WARNING: This operation is irreversible!
        """
        count = await sdk.clear_agents()
        return {"status": "cleared", "agents_deleted": count}

    @app.delete("/storage/results")
    async def clear_results():
        """
        DELETE ALL task results.

        WARNING: This operation is irreversible!
        """
        count = await sdk.clear_results()
        return {"status": "cleared", "results_deleted": count}

    @app.delete("/storage/metrics")
    async def clear_metrics():
        """
        DELETE ALL metrics.

        WARNING: This operation is irreversible!
        """
        count = await sdk.clear_metrics()
        return {"status": "cleared", "metrics_deleted": count}

    @app.delete("/storage/all")
    async def clear_all():
        """
        DELETE ALL DATA (agents, results, metrics, config).

        WARNING: This operation is irreversible!
        Use with extreme caution!
        """
        counts = await sdk.clear_all()
        return {"status": "cleared", "deleted_counts": counts}

    @app.get("/bus/streams")
    async def list_streams():
        """
        List all Redis streams and their message counts.

        Only works with RedisStreamEventBus.

        Returns:
            List of streams with their lengths
        """
        try:
            return await sdk.list_streams()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list streams: {e}")

    @app.get("/bus/inspect/{stream}")
    async def inspect_stream(stream: str, limit: int = 10):
        """
        Inspect recent messages in a Redis stream.

        Args:
            stream: Stream name (with or without 'omni-stream:' prefix)
            limit: Maximum number of messages to retrieve (default: 10)

        Returns:
            List of recent messages with IDs and data
        """
        try:
            return await sdk.inspect_stream(stream, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to inspect stream: {e}"
            )

    @app.get("/bus/groups/{stream}")
    async def list_groups(stream: str):
        """
        List consumer groups for a Redis stream.

        Args:
            stream: Stream name (with or without 'omni-stream:' prefix)

        Returns:
            List of consumer groups with their stats
        """
        try:
            return await sdk.list_groups(stream)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list groups: {e}")

    @app.get("/bus/dlq/{topic}")
    async def inspect_dlq(topic: str, limit: int = 10):
        """
        Inspect dead-letter queue entries for a topic.

        Args:
            topic: Topic name
            limit: Maximum number of entries to retrieve (default: 10)

        Returns:
            List of DLQ entries with IDs and data
        """
        try:
            return await sdk.inspect_dlq(topic, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to inspect DLQ: {e}")

    @app.get("/bus/stats")
    async def get_bus_stats():
        """
        Get comprehensive stats across all topics and consumer groups.

        Includes:
        - Stream lengths
        - Consumer group details
        - Pending message counts
        - DLQ statistics
        - Redis memory usage

        Returns:
            Comprehensive bus statistics
        """
        try:
            return await sdk.get_bus_stats()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get bus stats: {e}")

    return app


async def start_api_server(
    sdk: OmniDaemonSDK, host: str = "127.0.0.1", port: int = 8000
):
    """
    Start the FastAPI server in the background.
    Call this from sdk.run() or manually.
    """
    app = create_app(sdk)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
