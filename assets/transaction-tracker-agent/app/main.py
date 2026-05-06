# CRITICAL: Initialize telemetry BEFORE importing AI frameworks
try:
    from sap_cloud_sdk.aicore import set_aicore_config
    from sap_cloud_sdk.core.telemetry import auto_instrument
    set_aicore_config()
    auto_instrument()
except ImportError:
    # Running locally without SAP Cloud SDK
    print("Warning: SAP Cloud SDK not available, running without telemetry")

import logging
import os

import click
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import AgentExecutor
from opentelemetry.instrumentation.starlette import StarletteInstrumentor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))


@click.command()
@click.option("--host", default=HOST)
@click.option("--port", default=PORT)
def main(host: str, port: int):
    skill = AgentSkill(
        id="transaction-tracker-agent",
        name="transaction-tracker-agent",
        description="Retrieves transaction details and tenant information from the Transaction Tracker database by document ID",
        tags=["transaction", "tracker", "agent"],
        examples=["What are the details for document ID TXN-001?", "Which tenant processed document TXN-042?"],
    )
    agent_card = AgentCard(
        name="transaction-tracker-agent",
        description="Retrieves transaction details and tenant information from the Transaction Tracker database by document ID",
        url=os.environ.get("AGENT_PUBLIC_URL", f"http://{host}:{port}/"),
        version="1.0.0",
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        skills=[skill],
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=DefaultRequestHandler(
            agent_executor=AgentExecutor(),
            task_store=InMemoryTaskStore(),
        ),
    )
    app = server.build()

    # Add a simple test endpoint for direct HTTP testing
    from starlette.responses import JSONResponse
    from starlette.requests import Request
    from starlette.routing import Route
    from agent import SampleAgent

    test_agent = SampleAgent()

    async def test_query(request: Request):
        """Simple test endpoint for direct HTTP queries (not part of A2A protocol)."""
        try:
            data = await request.json()
            query = data.get("query", "")

            if not query:
                return JSONResponse(
                    {"error": "Missing 'query' field"},
                    status_code=400
                )

            # Use the agent's invoke method
            result = await test_agent.invoke(query, "test-session")

            return JSONResponse({
                "status": result.status,
                "query": query,
                "response": result.message
            })
        except Exception as e:
            logger.error(f"Test endpoint error: {e}")
            return JSONResponse(
                {"error": str(e)},
                status_code=500
            )

    async def test_health(request: Request):
        """Health check endpoint for testing."""
        return JSONResponse({
            "status": "healthy",
            "agent": "transaction-tracker-agent",
            "version": "1.0.0",
            "test_endpoint": "/test/query"
        })

    # Add routes to the app
    app.routes.append(Route("/test/query", test_query, methods=["POST"]))
    app.routes.append(Route("/test/health", test_health, methods=["GET"]))

    StarletteInstrumentor().instrument_app(app)

    logger.info(f"Starting A2A server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
