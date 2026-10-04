class DJIAssistantError(RuntimeError):
    """Base SDK error."""


class DJIAssistantNotRunning(DJIAssistantError):
    pass


class UIElementNotFound(DJIAssistantError):
    pass


class UnexpectedAssistantState(DJIAssistantError):
    pass


class FirmwareOperationFailed(DJIAssistantError):
    def __init__(self, code: str | None):
        self.code = code
        super().__init__(f"DJI Assistant reported Update failed. Code: {code or 'not provided'}")


class FirmwareOutcomeUnknown(DJIAssistantError):
    """A write may have started; never automatically retry."""
