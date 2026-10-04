from pywinauto.controls.uiawrapper import UIAWrapper

from ..backend.uia.session import UIASession


class BasePage:
    def __init__(self, session: UIASession):
        self.session = session

    @property
    def window(self) -> UIAWrapper:
        return self.session.window
