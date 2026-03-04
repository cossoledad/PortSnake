import os

import flet as ft

from portsnake.app_ui import main


if __name__ == "__main__":
    os.environ.setdefault("FLET_APP_HIDDEN", "false")
    ft.app(target=main, view=ft.AppView.FLET_APP)

