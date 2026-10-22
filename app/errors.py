class AppError(Exception):
    """Fachlicher Fehler mit deutscher Meldung für die Statusleiste."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Forbidden(AppError):
    def __init__(self, message: str = "Keine Berechtigung für diese Funktion."):
        super().__init__(message, 403)


class NotFound(AppError):
    def __init__(self, message: str = "Objekt nicht gefunden."):
        super().__init__(message, 404)
