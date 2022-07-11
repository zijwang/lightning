import lightning as L
from lightning.app.frontend.panel import PanelFrontend


class LitPanel(L.LightningFlow):

    def configure_layout(self):
        return PanelFrontend("panel_script.py")


class LitApp(L.LightningFlow):
    def __init__(self):
        super().__init__()
        self.lit_panel = LitPanel()

    def configure_layout(self):
        return {"name": "home", "content": self.lit_panel}


app = L.LightningApp(LitApp())
