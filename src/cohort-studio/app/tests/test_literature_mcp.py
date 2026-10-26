import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.test_e2e import app_url


def test_literature_tools_available_over_http_and_validate_inputs(app_url):
    async def check():
        async with streamable_http_client(app_url + '/mcp/') as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert {'search_pubmed', 'search_biorxiv'} <= names
                bad = await session.call_tool('search_pubmed', {'query': 'asthma', 'limit': 0})
                assert bad.is_error
                bad_date = await session.call_tool('search_biorxiv', {'query': 'genetics', 'start_date': 'invalid', 'end_date': '2024-01-02'})
                assert bad_date.is_error
    asyncio.run(check())
