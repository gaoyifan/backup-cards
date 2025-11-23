from textual.app import App
from frontend.screens import DashboardScreen
from frontend.client import GraphQLClient

class SDBackupApp(App):
    CSS = """
    .title {
        text-align: center;
        text-style: bold;
        margin: 1;
    }
    .buttons {
        align: center middle;
        height: auto;
        margin: 1;
    }
    Button {
        margin: 1;
    }
    .log-title {
        margin-top: 1;
        text-style: bold;
    }
    Log {
        border: solid green;
        height: 1fr;
    }
    Screen {
        align: center middle;
    }
    Container {
        width: 80%;
        height: 80%;
        border: solid white;
        padding: 1;
    }
    """

    def __init__(self, host=None, port=None, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.port = port

    def on_mount(self):
        host = self.host or "127.0.0.1"
        port = self.port or 8000
        self.client = GraphQLClient(host=host, port=port)
        self.push_screen(DashboardScreen(self.client))

if __name__ == "__main__":
    app = SDBackupApp()
    app.run()
