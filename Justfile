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