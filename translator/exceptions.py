class VeyoraTranslatorError(Exception):
    """Base exception for Veyora Translator"""
    pass

class TranscriptionError(VeyoraTranslatorError):
    """Raised when transcription fails"""
    pass

class TranslationError(VeyoraTranslatorError):
    """Raised when translation fails"""
    pass

class FFmpegError(VeyoraTranslatorError):
    """Raised when FFmpeg processing fails"""
    pass

class ModelNotFoundError(VeyoraTranslatorError):
    """Raised when a required model file is missing"""
    pass
