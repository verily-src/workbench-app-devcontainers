from agno_fastomop.observability.tracer import get_langfuse_client
from pathlib import Path
import asyncio
from agno.vectordb.lancedb import LanceDb
from agno.knowledge import Knowledge



# def bootstrap_prompts():
#     """Upload prompts to langfuse"""

#     langfuse = get_langfuse_client()
#     prompts_dir = Path(__file__).parent / "prompts"

#     required_prompts = [
#         ("database_agent", "database_agent.txt"),
#         ("semantic_agent", "semantic_agent_fastomop.txt"),
#         ("supervisor", "supervisor.txt"),
#     ]

#     for prompt_name, file_name in required_prompts:
#         prompt_path = prompts_dir / file_name

#         if not prompt_path.exists():
#             print(f"Error: Prompt file not found: {prompt_path}")
#             return False

#         prompt_content = prompt_path.read_text()

#         try:
#             # Create prompt with production label
#             prompt = langfuse.create_prompt(
#                 name=prompt_name,
#                 prompt=prompt_content,
#                 labels=["dev"],
#             )
#             print(f"Prompt '{prompt_name}' uploaded to Langfuse (version: {prompt.version})")

#         except Exception as e:
#             print(f"Error uploading prompt {prompt_name}: {e}")
#             # Try to continue with other prompts
#             continue

#     print("All prompts uploaded successfully")
#     return True

async def bootstrap_knowledge():
    """Load OMOP world model into LanceDB with lightweight embeddings"""

    from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder

    knowledge_dir = Path(__file__).parent / "knowledge" / "omop_world_model"

    if not knowledge_dir.exists():
        print(f"Error: Knowledge directory not found: {knowledge_dir}")
        return False

    print(f"Loading knowledge from: {knowledge_dir}")

    # Use lightweight embedder for SQL patterns (384 dimensions, fast, free)
    embedder = SentenceTransformerEmbedder(id="sentence-transformers/all-MiniLM-L6-v2")

    vectordb = LanceDb(
        uri=str(knowledge_dir / ".lancedb"),
        table_name="omop_world_model",
        embedder=embedder,
    )

    knowledge = Knowledge(
        vector_db=vectordb,
        max_results=5,
    )

    try:
        await knowledge.add_content_async(
            path=str(knowledge_dir),
            include=["*.md", "*.txt", "*.json"],
        )

        if hasattr(knowledge, 'contents_db') and knowledge.contents_db:
            content_count = len(knowledge.contents_db)
            print(f"✓ Knowledge base loaded: {content_count} documents")
        else:
            print("✓ Knowledge base loaded successfully")

        return True
    except Exception as e:
        print(f"Error loading knowledge base: {e}")
        return False

async def main():
    # prompts_uploaded = bootstrap_prompts()
    knowledge_uploaded = await bootstrap_knowledge()

    if prompts_uploaded and knowledge_uploaded:
        print("Bootstrap completed successfully")
    else:
        print("Bootstrap failed")

if __name__ == "__main__":
    asyncio.run(main())