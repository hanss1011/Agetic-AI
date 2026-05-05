#!/usr/bin/env python3
"""Test agent with visible logs"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# IMPORTANT: Configure logging BEFORE importing agent
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Setup
sys.path.insert(0, str(Path(__file__).parent / "app"))
os.environ["IBD_TESTING"] = "1"

from agent import SampleAgent

async def test_query(query):
    print("\n" + "="*80)
    print(f"TESTING: {query}")
    print("="*80)
    
    agent = SampleAgent()
    result = await agent.invoke(query, "test-session")
    
    print("\n--- FINAL RESPONSE ---")
    print(result.message)
    print("="*80 + "\n")

async def main():
    queries = [
        "Show me TXN-001",
        "Which tenant processed TXN-001?",
        "Show me TXN-999"
    ]
    
    for query in queries:
        await test_query(query)

if __name__ == "__main__":
    asyncio.run(main())
