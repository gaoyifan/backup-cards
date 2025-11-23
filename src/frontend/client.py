from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport
from gql.transport.aiohttp import AIOHTTPTransport
import logging

logger = logging.getLogger(__name__)

class GraphQLClient:
    def __init__(self, host="127.0.0.1", port=8000):
        self.url = f"ws://{host}:{port}/graphql"
        self.http_url = f"http://{host}:{port}/graphql"
        self.transport = WebsocketsTransport(url=self.url)
        self.client = Client(transport=self.transport, fetch_schema_from_transport=True)
        
        # Separate client for queries/mutations if needed, or use same if transport supports it.
        # gql WebsocketsTransport is mainly for subscriptions.
        # For queries/mutations, we might want AIOHTTPTransport.
        self.http_transport = AIOHTTPTransport(url=self.http_url)
        self.http_client = Client(transport=self.http_transport, fetch_schema_from_transport=True)

    async def execute(self, query_str, variable_values=None):
        query = gql(query_str)
        async with self.http_client as session:
            return await session.execute(query, variable_values=variable_values)

    async def subscribe(self, query_str, variable_values=None):
        query = gql(query_str)
        async with self.client as session:
            async for result in session.subscribe(query, variable_values=variable_values):
                yield result
