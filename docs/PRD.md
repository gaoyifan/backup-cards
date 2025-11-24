# Product Requirements Document: SD Backup Tool

## 1. Overview
The **SD Backup Tool** is a client-server application designed to automate and manage the backup of removable storage media (SD cards, USB drives) to local storage. It consists of a Python-based backend that exposes a GraphQL API and a Terminal User Interface (TUI) for monitoring and control.

## 2. Core Objectives
* Automate Data Safety: Automatically detect and back up inserted storage devices without user intervention.
* Visibility: Provide real-time feedback on backup progress.
* Control: Allow users to manually trigger, cancel, and configure backup operations.
* Flexibility: Support customizable backup paths, mount points, and headless operation.

## 3. Key Features

### 3.1 Backend System
* Device Monitoring: Automatically detects when a new storage device is connected.
* Backup Engine:
    * Uses `rsync` for efficient, incremental file transfer.
    * Supports manual start and cancellation of backup tasks.
    * Handles mounting and unmounting of devices.
* GraphQL API: See `docs/api.grapgql`.

### 3.2 Frontend (TUI)
* Framework: Built with **Textual** for a rich terminal experience.
* Dashboard: Visualizes backup status, progress, logs, and configuration.
* Interactivity: Provides commands to trigger manual backups or cancel running tasks.
* Configuration: Allows users to modify settings.
* Live Updates: Subscribes to backup progress via GraphQL subscriptions to update the UI in real-time.

### 3.3 Configuration
Configurable via CLI.

#### Template Variables
The system supports dynamic target path generation using the following variables:

*   `{date}`: The date (`YYYYMMDD`) derived from the earliest modification time of files on the device (or current date if scanning fails).
*   `{hour}`: The hour (`HH`) derived from the earliest modification time.
*   `{minute}`: The minute (`MM`) derived from the earliest modification time.
*   `{uuid}`: The full filesystem UUID of the device.
*   `{uuid_short}`: The first 4 characters of the device UUID.

## 4. Technical Stack
### 4.0 Overview
* OS: Linux
* Language: Python (Async)
* Project Manager: uv

### 4.1 Entry Point (`/main.py`)
* Logging: Loguru
* CLI: Typer
* Web Server: Uvicorn

### 4.2 Backend (`/src/backend`)
* API: FastAPI, Strawberry (GraphQL)
* Database: SQLAlchemy, SQLite
* System Tools: rsync, psutil

### 4.3 Frontend (`/src/frontend`)
* Framework: Textual
* Dashboard: Visualizes backup status, progress, logs, and configuration.
* Interactivity: Provides commands to trigger manual backups or cancel running tasks.
* Configuration: Allows users to modify settings.
* Live Updates: Subscribes to backup progress via GraphQL subscriptions to update the UI in real-time.

### 4.4 GraphQL API
See `docs/api.graphql`.

## 5. User Flows
1. Automatic Flow: User inserts SD card → System detects device → Mounts to generated path → Backs up to target → Unmounts → Updates Log.
2. Manual Flow: User launches TUI → Reviews Status → Triggers "Start Backup" → Watches real-time logs → Backup completes.
3. Headless Mode: Backend runs as a service, performing backups silently while logging activities for later review.

## 6. Continuous test cases (`/tests`)
### 6.1 Manual Backup from dir to dir
1. Mock a dir with files
2. Mock a target dir
3. Trigger backup
4. Check backup result

### 6.2 Manual Backup from device to dir
1. Mock a loopback device with files
2. Mock a target dir
3. Trigger backup
4. Check backup result

### 6.3 Template Variable Test
1. Mock a loopback device with files
2. Trigger backup with different template variables
3. Check backup result
