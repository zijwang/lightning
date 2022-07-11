# app.py
import panel as pn

# Todo: change import
# from lightning_app.frontend.panel import PanelFrontend
from lightning.app.frontend.panel import PanelFrontend


import lightning as L


def your_panel_app(app):
    return pn.pane.Markdown("hello")


class LitPanel(L.LightningFlow):

    def configure_layout(self):
        return PanelFrontend(your_panel_app)


class LitApp(L.LightningFlow):
    def __init__(self):
        super().__init__()
        self.lit_panel = LitPanel()

    def configure_layout(self):
        return {"name": "home", "content": self.lit_panel}


app = L.LightningApp(LitApp())
