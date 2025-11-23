import asyncio
import os
import shutil
import time
import subprocess
import requests
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from config import load_config

# Setup paths
TEST_DIR = "/tmp/sd-backup-test"
SOURCE_DIR = os.path.join(TEST_DIR, "source")
TARGET_DIR = os.path.join(TEST_DIR, "target")
PORT_FILE = ".port"

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

async def run_test():
    print("Starting E2E Test...")
    setup_directories()
    
    # Remove existing port file
    if os.path.exists(PORT_FILE):
        os.remove(PORT_FILE)

    # Start main.py in headless mode
    print("Starting backend subprocess...")
    process = subprocess.Popen(
        ["uv", "run", "python", "src/main.py", "--headless"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        # Wait for port file
        port = None
        for _ in range(10):
            if os.path.exists(PORT_FILE):
                with open(PORT_FILE, "r") as f:
                    content = f.read().strip()
                    if content:
                        port = int(content)
                        break
            time.sleep(1)
        
        if port is None:
            print("Timed out waiting for .port file")
            # Print stdout/stderr for debugging
            stdout, stderr = process.communicate(timeout=1)
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            exit(1)
            
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
        
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)

if __name__ == "__main__":
    asyncio.run(run_test())
