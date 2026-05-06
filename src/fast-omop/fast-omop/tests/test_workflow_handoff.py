"""
Test what gets passed between agents in the workflow
"""
import asyncio
from agno_fastomop.workflows.omop_workflow import initialize_workflow


async def test_workflow_handoff():
    """Test inter-agent communication"""

    workflow = await initialize_workflow()

    query = "How many patients have diabetes?"

    print("Running workflow with message passing inspection...")
    print("="*50)

    response = await workflow.arun(query, stream=True)

    print("\n" + "="*50)
    print("WORKFLOW RESPONSE:")
    print("="*50)

    async for event in response:
        if hasattr(event, 'event'):
            print(f"\nEvent: {event.event}")

        if hasattr(event, 'step_name'):
            print(f"Step: {event.step_name}")

        if hasattr(event, 'content') and event.content:
            print(f"Content preview: {str(event.content)[:200]}...")

        if hasattr(event, 'step_output') and event.step_output:
            print(f"\nStep Output:")
            print(f"  Type: {type(event.step_output)}")
            if hasattr(event.step_output, 'content'):
                print(f"  Content: {event.step_output.content[:500]}...")


if __name__ == "__main__":
    asyncio.run(test_workflow_handoff())
