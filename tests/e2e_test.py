import asyncio
import os
import shutil
import time
import subprocess
import requests
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
import socket

# Setup paths
TEST_DIR = "/tmp/sd-backup-test"
SOURCE_DIR = os.path.join(TEST_DIR, "source")
TARGET_DIR = os.path.join(TEST_DIR, "target")

def setup_directories():
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    os.makedirs(SOURCE_DIR)
    os.makedirs(TARGET_DIR)
    
    # Create dummy files
    with open(os.path.join(SOURCE_DIR, "file1.txt"), "w") as f:
        f.write("content1")
    with open(os.path.join(SOURCE_DIR, "file2.txt"), "w") as f:
        f.write("content2")

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def wait_for_server(host, port, timeout=10):
    url = f"http://{host}:{port}/graphql"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.post(url, json={"query": "{ __typename }"}, timeout=1)
            if response.status_code in {200, 400}:
                return
        except requests.RequestException:
            time.sleep(0.5)
            continue
    raise TimeoutError(f"Backend not reachable at {url} after {timeout} seconds")

async def run_test():
    print("Starting E2E Test...")
    setup_directories()
    
    port = find_free_port()

    # Start main.py in headless mode
    print("Starting backend subprocess...")
    process = subprocess.Popen(
        ["uv", "run", "python", "src/main.py", "--headless", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        wait_for_server("127.0.0.1", port)
        print(f"Backend running on port {port}")
        
        transport = AIOHTTPTransport(url=f"http://127.0.0.1:{port}/graphql")
        client = Client(transport=transport, fetch_schema_from_transport=True)
        
        print("Triggering manual backup...")
        query = gql("""
            mutation($source: String!, $target: String!) {
                startManualBackup(source: $source, target: $target)
            }
        """)
        
        result = await client.execute_async(query, variable_values={"source": SOURCE_DIR, "target": TARGET_DIR})
        print(f"Mutation result: {result}")
        
        # Wait for backup to complete (it's async in backend)
        print("Waiting for backup to complete...")
        time.sleep(2)
        
        # Verify files
        print("Verifying files...")
        files = os.listdir(TARGET_DIR)
        if "file1.txt" in files and "file2.txt" in files:
            print("SUCCESS: Files found in target.")
        else:
            print(f"FAILURE: Files missing in target. Found: {files}")
            exit(1)
            
    finally:
        print("Terminating backend...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

if __name__ == "__main__":
    asyncio.run(run_test())
