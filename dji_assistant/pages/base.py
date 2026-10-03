class BasePage:
    def __init__(self, session):
        self.session = session

    @property
    def window(self):
        return self.session.window
