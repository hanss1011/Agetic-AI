"""
Interactive chat interface for testing the Transaction Tracker Agent.

This script provides a simple command-line chat interface to test the agent
with realistic queries using mock data.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add app directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "app"))

# Configure logging - Show INFO level to see agent workflow
logging.basicConfig(
    level=logging.INFO,  # Show agent steps and tool calls
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Run interactive chat with the agent."""
    # Load .env file first
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    # Enable mock mode
    os.environ["IBD_TESTING"] = "1"

    print("=" * 70)
    print("Transaction Tracker Agent - Interactive Chat")
    print("=" * 70)
    print("\nMode: Mock Data (IBD_TESTING=1)")
    print("\nAvailable document IDs to test:")
    print("  • ff6257db-05a0-4471-ba4f-6a571b67b9af (status: Received)")
    print("  • FA163E51-A3F5-1FE1-9298-BD5598484262 (status: Completed, with details)")
    print("  • abc-123-success (status: Success)")
    print("  • err-456-failed (status: Failed)")
    print("  • proc-789-processing (status: Processing)")
    print("  • TXN-999 (not found)")
    print("\nExample queries:")
    print("  • What's the status of ff6257db-05a0-4471-ba4f-6a571b67b9af?")
    print("  • Show me detailed info for FA163E51-A3F5-1FE1-9298-BD5598484262")
    print("  • Which tenant processed abc-123-success?")
    print("  • Find TXN-999")
    print("\nType 'quit' or 'exit' to stop.")
    print("=" * 70)

    # Import agent
    from agent import SampleAgent

    # Initialize agent
    print("\n🤖 Initializing agent...")
    agent = SampleAgent()
    print("✅ Agent ready!\n")

    # Chat loop
    while True:
        try:
            # Get user input
            print("\n" + "─" * 70)
            query = input("\n💬 You: ").strip()

            if not query:
                continue

            # Check for exit commands
            if query.lower() in ['quit', 'exit', 'bye', 'q']:
                print("\n👋 Goodbye!")
                break

            # Process query
            print("\n🤖 Agent: ", end="", flush=True)

            # Use invoke for simpler synchronous-style response
            response = await agent.invoke(query, context_id="chat-session")

            if response.status == "completed":
                print(response.message)
            elif response.status == "error":
                print(f"\n❌ Error: {response.message}")
            else:
                print(f"\n⚠️  Status: {response.status}")
                print(response.message)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            logger.error("Chat error: %s", e, exc_info=True)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    # Load .env file to check LLM configuration
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    # Check if LLM is configured
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("AICORE_CLIENT_ID"):
        print("\n⚠️  WARNING: No LLM configured!")
        print("\nTo use the chat interface, you need to configure an LLM:")
        print("\nOption 1: OpenAI")
        print("  export OPENAI_API_KEY=your-api-key")
        print("  Update .env: LITELLM_MODEL=gpt-4o-mini")
        print("\nOption 2: SAP AI Core")
        print("  Set AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_AUTH_URL, AICORE_BASE_URL")
        print("\nFor now, you can test the tools directly with test_transaction_detail.py")
        print("=" * 70)
        sys.exit(1)

    try:
        asyncio.run(main())
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
