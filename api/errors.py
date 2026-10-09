class AnalysisError(Exception):
    """Public, sanitized errors, separate from provider exception text."""

    def __init__(self, code, message, status=502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
