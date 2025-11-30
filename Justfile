build:
  uv run pyinstaller app.py \
      --noconfirm \
      --name "SD Backup" \
      --windowed \
      --paths src \
      --paths . \
      --hidden-import aiosqlite \
      --hidden-import textual.drivers.web_driver \
      --collect-data textual_serve \
      --osx-bundle-identifier com.sd-backup.app

clean:
  rm -rf dist

rebuild: clean build

tui:
  uv run python app.py --log-path /dev/null tui

web:
  uv run python app.py web --with-webview

daemon:
  uv run python app.py daemon

connect host port:
  uv run python app.py connect {{host}} {{port}}

fmt:
  uv run autoflake --remove-all-unused-imports --remove-unused-variables --recursive --in-place src tests
  uv run isort -l 150 src tests
  uv run black -l 150 src tests