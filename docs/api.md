# SD Backup Tool - API Documentation

## Overview

The SD Backup Tool exposes a GraphQL API served by FastAPI. The API is available at `/graphql` endpoint on the configured host and port.

**Base URL:** `http://{graphql_host}:{graphql_port}/graphql`

**Default:** `http://127.0.0.1:{dynamic_port}/graphql`

## Transport

- **Queries/Mutations:** HTTP POST
- **Subscriptions:** WebSocket

## Schema

### Types

#### Config
Configuration object for user-defined settings.

```graphql
type Config {
  autoBackupEnabled: Boolean!
  autoBackupTargetPath: String!
  excludePatterns: [String!]!
  includePatterns: [String!]!
}
```

**Fields:**
- `autoBackupEnabled`: Whether automatic backup on device insertion is enabled
- `autoBackupTargetPath`: Target path template with variables like `{date}`, `{uuid_short}`, `{model}` (spaces in `{model}` become `-`)
- `excludePatterns`: List of rsync exclude patterns (e.g., `["*.tmp", ".DS_Store"]`)
- `includePatterns`: List of rsync include patterns (processed first)

#### BackupStatus
Current backup status.

```graphql
type BackupStatus {
  active: Boolean!
  message: String!
}
```

**Fields:**
- `active`: Whether a backup is currently running
- `message`: Status message (e.g., "Idle", "Backup in progress")

#### LogEntry
A single log entry.

```graphql
type LogEntry {
  message: String!
}
```

### Queries

#### autoBackupSupported
Check if auto backup is supported on this platform.

```graphql
query {
  autoBackupSupported
}
```

**Returns:** `Boolean!`

**Example Response:**
```json
{
  "data": {
    "autoBackupSupported": true
  }
}
```

**Notes:**
- Returns `true` only when running on Linux (requires pyudev for device monitoring)
- This is a read-only system capability, not a user configuration

#### config
Get current configuration.

```graphql
query {
  config {
    autoBackupEnabled
    autoBackupTargetPath
    excludePatterns
    includePatterns
  }
}
```

**Returns:** `Config!`

**Example Response:**
```json
{
  "data": {
    "config": {
      "autoBackupEnabled": true,
      "autoBackupTargetPath": "~/sd-backups/{date}-{uuid_short}",
      "excludePatterns": [".DS_Store", "Thumbs.db", "*.tmp"],
      "includePatterns": []
    }
  }
}
```

#### logs
Get all accumulated logs.

```graphql
query {
  logs {
    message
  }
}
```

**Returns:** `[LogEntry!]!`

**Example Response:**
```json
{
  "data": {
    "logs": [
      {"message": "Backend started"},
      {"message": "Device detected: /dev/sdb1"},
      {"message": "Backup completed successfully"}
    ]
  }
}
```

#### currentStatus
Get current backup status.

```graphql
query {
  currentStatus {
    active
    message
  }
}
```

**Returns:** `BackupStatus!`

**Example Response:**
```json
{
  "data": {
    "currentStatus": {
      "active": false,
      "message": "Idle"
    }
  }
}
```

### Mutations

#### startManualBackup
Start a manual backup operation.

```graphql
mutation($source: String!, $target: String!) {
  startManualBackup(source: $source, target: $target)
}
```

**Parameters:**
- `source` (String!): Source directory path
- `target` (String!): Target directory path

**Returns:** `String!` - Status message

**Example:**
```graphql
mutation {
  startManualBackup(
    source: "/media/sd-backup-1234",
    target: "/home/user/backups/20231123"
  )
}
```

**Example Response:**
```json
{
  "data": {
    "startManualBackup": "Backup started"
  }
}
```

**Notes:**
- Backup runs in background thread
- Returns immediately, use subscription for progress
- Will fail if backup already in progress

#### cancelBackup
Cancel the currently running backup.

```graphql
mutation {
  cancelBackup
}
```

**Returns:** `String!` - Status message

**Example Response:**
```json
{
  "data": {
    "cancelBackup": "Backup cancelled"
  }
}
```

**Notes:**
- Terminates the rsync process
- Safe to call even if no backup is running

#### updateConfig
Update configuration values.

```graphql
mutation UpdateConfig($config: ConfigInput!) {
  updateConfig(config: $config)
}
```

**Input Type:**
```graphql
input ConfigInput {
  autoBackupEnabled: Boolean
  autoBackupTargetPath: String
  excludePatterns: [String!]
  includePatterns: [String!]
}
```

**Returns:** `Boolean!` - True if update succeeded

**Example:**
```graphql
mutation {
  updateConfig(config: {
    autoBackupEnabled: true,
    autoBackupTargetPath: "~/backups/{date}/{hour}",
    excludePatterns: [".DS_Store", "*.tmp"],
    includePatterns: ["*.CR2", "*.jpg"]
  })
}
```

**Example Response:**
```json
{
  "data": {
    "updateConfig": true
  }
}
```

**Notes:**
- Changes are immediately persisted to the SQLite runtime config (`--db-path`)
- CLI options such as listen address/port still require a restart to take effect
- Include patterns are processed first by rsync, then exclude patterns
- Only provided fields are updated; omitted fields retain their current values

### Subscriptions

#### backupProgress
Subscribe to backup progress updates and log messages.

```graphql
subscription {
  backupProgress
}
```

**Returns:** Stream of `String!` messages

**Example:**
```graphql
subscription {
  backupProgress
}
```

**Example Stream:**
```json
{"data": {"backupProgress": "Device detected: /dev/sdb1"}}
{"data": {"backupProgress": "Mounted at /media/sd-backup-1234"}}
{"data": {"backupProgress": "Starting automatic backup to ~/backups/20231123"}}
{"data": {"backupProgress": "Automatic backup completed"}}
```

**Notes:**
- Uses WebSocket transport
- Emits all log messages in real-time
- Stays connected until client disconnects

## Client Examples

### Python (gql)

```python
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.websockets import WebsocketsTransport

# HTTP client for queries/mutations
http_transport = AIOHTTPTransport(url="http://127.0.0.1:8000/graphql")
http_client = Client(transport=http_transport)

# Query example
query = gql("""
    query {
        currentStatus {
            active
            message
        }
    }
""")
result = await http_client.execute_async(query)

# Mutation example
mutation = gql("""
    mutation($source: String!, $target: String!) {
        startManualBackup(source: $source, target: $target)
    }
""")
result = await http_client.execute_async(
    mutation,
    variable_values={"source": "/src", "target": "/dst"}
)

# WebSocket client for subscriptions
ws_transport = WebsocketsTransport(url="ws://127.0.0.1:8000/graphql")
ws_client = Client(transport=ws_transport)

# Subscription example
subscription = gql("""
    subscription {
        backupProgress
    }
""")
async with ws_client as session:
    async for result in session.subscribe(subscription):
        print(result["backupProgress"])
```

### cURL

**Query:**
```bash
curl -X POST http://127.0.0.1:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ currentStatus { active message } }"}'
```

**Mutation:**
```bash
curl -X POST http://127.0.0.1:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($source: String!, $target: String!) { startManualBackup(source: $source, target: $target) }",
    "variables": {"source": "/src", "target": "/dst"}
  }'
```

### JavaScript (fetch)

```javascript
// Query
const response = await fetch('http://127.0.0.1:8000/graphql', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    query: `{
      currentStatus {
        active
        message
      }
    }`
  })
});
const data = await response.json();

// Mutation
const response = await fetch('http://127.0.0.1:8000/graphql', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    query: `mutation($source: String!, $target: String!) {
      startManualBackup(source: $source, target: $target)
    }`,
    variables: {source: "/src", target: "/dst"}
  })
});
```

## Error Handling

The API returns standard GraphQL error responses:

```json
{
  "data": null,
  "errors": [
    {
      "message": "Failed to start backup: A backup is already in progress.",
      "locations": [{"line": 2, "column": 3}],
      "path": ["startManualBackup"]
    }
  ]
}
```

**Common Error Cases:**
- Backup already in progress
- Invalid source/target paths
- Permission denied (mount/rsync)
- Invalid configuration key
- Type conversion errors

## GraphQL Playground

When running the backend, you can access the GraphQL playground at:

`http://{graphql_host}:{graphql_port}/graphql`

This provides:
- Interactive schema explorer
- Query/mutation editor with autocomplete
- Documentation browser
- Subscription testing

## Rate Limiting

Currently, no rate limiting is implemented. All clients on localhost have unrestricted access.

## Authentication

Currently, no authentication is required. The API assumes it's running on localhost and accessed by trusted clients.

## Versioning

API versioning is not currently implemented. Breaking changes will be documented in release notes.
