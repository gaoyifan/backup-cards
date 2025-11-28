import asyncio
import logging

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport
from gql.transport.aiohttp import AIOHTTPTransport

logger = logging.getLogger(__name__)


class GraphQLClient:
    def __init__(self, host="127.0.0.1", port=8000):
        self.ws_url = f"ws://{host}:{port}/graphql"
        self.http_url = f"http://{host}:{port}/graphql"
        logger.debug("GraphQLClient initialized: http=%s, ws=%s", self.http_url, self.ws_url)
        self._http_lock = asyncio.Lock()

    async def execute(self, query_str, variable_values=None):
        logger.debug("Executing GraphQL query: %s", query_str[:100].replace('\n', ' '))
        query = gql(query_str)
        try:
            async with self._http_lock:
                transport = AIOHTTPTransport(url=self.http_url)
                client = Client(transport=transport, fetch_schema_from_transport=False)
                async with client as session:
                    result = await session.execute(query, variable_values=variable_values)
                    logger.debug("GraphQL query successful")
                    return result
        except Exception as e:
            logger.error("GraphQL query failed: %s", e)
            raise

    async def subscribe(self, query_str, variable_values=None):
        logger.debug("Starting GraphQL subscription: %s", query_str[:100].replace('\n', ' '))
        query = gql(query_str)
        # Create a new transport and client for each subscription
        # This allows multiple concurrent subscriptions
        transport = WebsocketsTransport(url=self.ws_url)
        client = Client(transport=transport, fetch_schema_from_transport=False)
        try:
            async with client as session:
                async for result in session.subscribe(query, variable_values=variable_values):
                    yield result
        except Exception as e:
            logger.error("GraphQL subscription failed: %s", e)
            raise
