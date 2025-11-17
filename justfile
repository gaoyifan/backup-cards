# Task runner for this project

# Use a strict shell for all recipes
set shell := ["bash", "-euo", "pipefail", "-c"]

# Config
app_name := "Backup Cards"
bundle_id := "com.example.backupcards"

# Default target prints the recipe list
default: help

help:
	@echo "Available tasks:"
	@just --list

# Ensure local environment is synchronized
setup:
	uv sync

# Build macOS .app bundle with PyInstaller
build:
	uv run pyinstaller \
		--windowed \
		--name "{{app_name}}" \
		--osx-bundle-identifier {{bundle_id}} \
		--collect-all nicegui \
		--collect-all pywebview \
		--noconfirm \
		main.py

# Open the built .app in Finder
open-app:
	open "dist/{{app_name}}.app"

# Run the GUI directly via Python
run:
	uv run main.py

# Remove build artifacts
clean:
	rm -rf build dist
	rm -f *.spec

# Clean and then build
rebuild: clean build
