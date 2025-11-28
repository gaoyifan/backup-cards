#!/usr/bin/env python3
import os
import sys
import json
import time
import datetime
import subprocess
import argparse
import logging
import requests
import signal
import pyudev
import string
import random
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
DEFAULT_BACKUP_DIR = os.path.expanduser("~/backups")
BACKUP_DIR = os.path.expanduser(os.getenv('BACKUP_DIR', DEFAULT_BACKUP_DIR))
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TARGET_DEVICE = os.getenv('TARGET_DEVICE')
# Remote backup settings
REMOTE_BACKUP_ENABLED = os.getenv('REMOTE_BACKUP_ENABLED', 'false').lower() == 'true'
REMOTE_BACKUP_PATH = os.getenv('REMOTE_BACKUP_PATH')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("sd-auto-backup")

# Suppress unnecessary warnings
logging.getLogger("urllib3").setLevel(logging.WARNING)
# Suppress pyudev deprecation warnings
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pyudev")

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

# Log configuration (excluding sensitive information)
logger.info(f"Backup directory: {BACKUP_DIR}")
logger.info(f"Telegram configured: {bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)}")
logger.info(f"Remote backup: {'enabled' if REMOTE_BACKUP_ENABLED else 'disabled'}")
if REMOTE_BACKUP_ENABLED:
    logger.info(f"Remote backup path: {REMOTE_BACKUP_PATH}")


def send_telegram_message(message):
    """Send a message to the specified Telegram chat."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        logger.warning("Telegram notification skipped: missing credentials")
        return False

    try:
        logger.info(f"Sending Telegram notification: {message[:30]}...")
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        url = f"{api_url}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data)
        if response.status_code != 200:
            logger.error(f"Failed to send Telegram message: {response.text}")
            return False
        logger.info("Telegram notification sent successfully")
        return True
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False


def generate_identifier():
    """Generate a random 8-character identifier (uppercase letters and digits)."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(8))


def get_mount_point(device_path):
    """Get the mount point for a device if mounted."""
    try:
        result = subprocess.run(
            ["findmnt", "-S", device_path, "-o", "TARGET", "-n"],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception as e:
        logger.error(f"Error getting mount point: {e}")
        return None


def mount_device(device_path):
    """Mount the device to a temporary location."""
    mount_point = f"/tmp/sd-backup-{int(time.time())}"
    os.makedirs(mount_point, exist_ok=True)

    try:
        # Try to determine filesystem type
        result = subprocess.run(
            ["blkid", "-o", "value", "-s", "TYPE", device_path],
            capture_output=True, text=True
        )

        mount_cmd = ["mount", device_path, mount_point]

        # Add filesystem type if detected
        if result.returncode == 0 and result.stdout.strip():
            fs_type = result.stdout.strip()
            logger.info(f"Detected filesystem type: {fs_type}")
            mount_cmd = ["mount", "-t", fs_type, device_path, mount_point]

        logger.info(f"Mounting with command: {' '.join(mount_cmd)}")
        subprocess.run(mount_cmd, check=True)

        logger.info(f"Mounted {device_path} to {mount_point}")
        return mount_point
    except Exception as e:
        logger.error(f"Error mounting device: {e}")
        return None


def unmount_device(mount_point):
    """Unmount the device."""
    try:
        subprocess.run(
            ["umount", mount_point], 
            check=True
        )
        logger.info(f"Unmounted from {mount_point}")
        return True
    except Exception as e:
        logger.error(f"Error unmounting device: {e}")
        return False

def get_device_partitions(device_node):
    """Get all partitions for a device"""
    partitions = []
    try:
        # Use lsblk to get partitions
        result = subprocess.run(
            ["lsblk", "-nplo", "NAME", device_node],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            # First line is the device itself, skip it
            if len(lines) > 1:
                partitions = [line.strip() for line in lines[1:] if os.path.exists(line.strip())]
                logger.info(f"Found partitions for {device_node}: {partitions}")
    except Exception as e:
        logger.error(f"Error getting partitions for {device_node}: {e}")

    return partitions


def backup_device(device_path):
    """Perform the backup operation on the given device."""
    # Check if device exists
    if not os.path.exists(device_path):
        logger.error(f"Device {device_path} does not exist")
        return False

    logger.info(f"Starting backup for device {device_path}")

    # Check if the device is already mounted
    mount_point = get_mount_point(device_path)
    mount_created = False

    if not mount_point:
        mount_point = mount_device(device_path)
        if not mount_point:
            logger.error(f"Failed to mount {device_path}")
            send_telegram_message(f"❌ Failed to mount SD card at {device_path}")
            return False
        mount_created = True

    try:
        # Create or read the timestamp file
        timestamp_file = os.path.join(mount_point, ".sd-backup-info.json")

        if os.path.exists(timestamp_file):
            # Read existing timestamp and identifier
            with open(timestamp_file, 'r') as f:
                backup_info = json.load(f)
            first_seen = backup_info['first_seen']
            identifier = backup_info['identifier']
            logger.info(f"Found existing backup info: first seen at {first_seen}, identifier: {identifier}")
        else:
            # Create new timestamp and identifier
            first_seen = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            identifier = generate_identifier()
            backup_info = {
                'first_seen': first_seen,
                'identifier': identifier,
                'device_path': device_path,
                'created_on': datetime.datetime.now().isoformat()
            }
            with open(timestamp_file, 'w') as f:
                json.dump(backup_info, f, indent=2)
            logger.info(f"Created new backup info: first seen at {first_seen}, identifier: {identifier}")

        # Create backup directory
        backup_folder_name = f"{first_seen}-{identifier}"
        backup_path = os.path.join(BACKUP_DIR, backup_folder_name)

        # If remote backup is enabled, modify the backup path
        remote_path = ""
        if REMOTE_BACKUP_ENABLED:
            remote_path = f"{REMOTE_BACKUP_PATH}{backup_folder_name}/"
            logger.info(f"Using remote backup path: {remote_path}")
        else:
            # Create local directory
            os.makedirs(backup_path, exist_ok=True)

        # Send notification for backup start
        start_message = (
            f"🔄 SD Card Backup Started\n"
            f"Device: <code>{device_path}</code>\n"
            f"Identifier: <code>{identifier}</code>\n"
            f"Backup Location: <code>{remote_path or backup_path}</code>"
        )
        send_telegram_message(start_message)

        # Perform rsync backup
        logger.info(f"Starting backup from {mount_point} to {remote_path or backup_path}")

        start_time = time.time()

        if REMOTE_BACKUP_ENABLED:
            # Remote rsync to SSH server
            result = subprocess.run(
                ["rsync", "-rlptv", f"{mount_point}/", remote_path],
                capture_output=True, text=True
            )
        else:
            # Local rsync
            result = subprocess.run(
                ["rsync", "-rlptv", f"{mount_point}/", backup_path],
                capture_output=True, text=True
            )

        if result.returncode != 0:
            logger.error(f"Backup failed: {result.stderr}")
            send_telegram_message(f"❌ Backup failed for SD card {identifier}:\n{result.stderr}")
            return False

        duration = time.time() - start_time
        logger.info(f"Backup completed in {duration:.2f} seconds")

        # Send notification for backup completion
        complete_message = (
            f"✅ SD Card Backup Completed\n"
            f"Device: <code>{device_path}</code>\n"
            f"Identifier: <code>{identifier}</code>\n"
            f"Backup Location: <code>{remote_path or backup_path}</code>\n"
            f"Duration: {duration:.2f} seconds"
        )
        send_telegram_message(complete_message)

        return True

    except Exception as e:
        logger.error(f"Error during backup: {e}")
        send_telegram_message(f"❌ Backup error for SD card:\n{str(e)}")
        return False

    finally:
        # Unmount if we mounted it
        if mount_created:
            unmount_device(mount_point)

def is_storage_device(device, action=None):
    """Determine if the device is a storage device"""
    # Check various attributes to determine if it's a storage device
    try:
        return all([
            device.subsystem == "block",
            getattr(device, "action") == action,
            device.device_type == "partition",
            device.get("ID_BUS") == "usb",
            device.sys_number == "1",
            device.get("ID_FS_TYPE", "").lower() in {"exfat", "vfat", "udf"},
        ])
    except Exception as e:
        logger.error(f"Error matching device: {e}")
        return False


def process_device(device):
    """Process a device and decide if and how to back it up."""
    device_node = device.device_node

    logger.info(f"Processing device: {device_node}")

    backup_device(device_node)


def monitor_devices():
    """Monitor for new SD cards in daemon mode."""
    logger.info("Starting SD card monitoring daemon")
    send_telegram_message("🔄 SD card backup service started")

    # Set up signal handling
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received, exiting...")
        send_telegram_message("🛑 SD card backup service is shutting down")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create monitor
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='block', device_type='partition')
    monitor.start()

    logger.info("Checking existing storage partitions...")
    for device in context.list_devices(subsystem='block', DEVTYPE='partition'):
        if is_storage_device(device):  # action==None for existing partitions
            process_device(device)

    logger.info("Listening for block/partition events...")

    try:
        for _action, device in monitor:
            if is_storage_device(device, action='add'):
                process_device(device)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        logger.info("Stopping device monitor")
        send_telegram_message("🛑 SD card backup service stopped")


def main():
    parser = argparse.ArgumentParser(description="SD Card Auto Backup Tool")
    parser.add_argument("--mode", choices=['oneshot', 'daemon'], 
                       default='daemon', help="Operation mode: oneshot or daemon")
    parser.add_argument("--remote", action="store_true", 
                       help="Enable remote backup (overrides environment setting)")

    args = parser.parse_args()

    # Override remote backup setting if specified
    global REMOTE_BACKUP_ENABLED
    if args.remote:
        REMOTE_BACKUP_ENABLED = True
        logger.info("Remote backup enabled via command line argument")

    if args.mode == 'daemon':
        monitor_devices()
    else:  # oneshot mode
        if not TARGET_DEVICE:
            logger.error("No target device specified in .env file for one-shot mode")
            return 1

        if not os.path.exists(TARGET_DEVICE):
            logger.error(f"Device {TARGET_DEVICE} not found")
            return 1

        success = backup_device(TARGET_DEVICE)
        return 0 if success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
