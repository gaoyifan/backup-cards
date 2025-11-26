import asyncio
import logging

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport
from gql.transport.aiohttp import AIOHTTPTransport

logger = logging.getLogger(__name__)


class GraphQLClient:
    def __init__(self, host="127.0.0.1", port=8000):
        self.url = f"ws://{host}:{port}/graphql"
        self.http_url = f"http://{host}:{port}/graphql"
        logger.debug("GraphQLClient initialized: http=%s, ws=%s", self.http_url, self.url)
        self.transport = WebsocketsTransport(url=self.url)
        self.client = Client(transport=self.transport, fetch_schema_from_transport=True)
        self._http_lock = asyncio.Lock()
        
        # Separate client for queries/mutations if needed, or use same if transport supports it.
        # gql WebsocketsTransport is mainly for subscriptions.
        # For queries/mutations, we might want AIOHTTPTransport.
        self.http_transport = AIOHTTPTransport(url=self.http_url)
        self.http_client = Client(transport=self.http_transport, fetch_schema_from_transport=True)

    async def execute(self, query_str, variable_values=None):
        logger.debug("Executing GraphQL query: %s", query_str[:100].replace('\n', ' '))
        query = gql(query_str)
        try:
            async with self._http_lock:
                async with self.http_client as session:
                    result = await session.execute(query, variable_values=variable_values)
                    logger.debug("GraphQL query successful")
                    return result
        except Exception as e:
            logger.error("GraphQL query failed: %s", e)
            raise

    async def subscribe(self, query_str, variable_values=None):
        logger.debug("Starting GraphQL subscription: %s", query_str[:100].replace('\n', ' '))
        query = gql(query_str)
        try:
            async with self.client as session:
                async for result in session.subscribe(query, variable_values=variable_values):
                    yield result
        except Exception as e:
            logger.error("GraphQL subscription failed: %s", e)
            raise
