class DJIAssistantError(RuntimeError):
    """Base SDK error."""


class DJIAssistantNotRunning(DJIAssistantError):
    pass


class UIElementNotFound(DJIAssistantError):
    pass


class UnexpectedAssistantState(DJIAssistantError):
    pass
