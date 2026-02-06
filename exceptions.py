"""
beanJAMinBOT Exception Hierarchy

Organized by domain and recoverability:
- Recoverable: Network issues, rate limits, temporary failures
- Non-recoverable: Auth failures, missing config
"""


class BotException(Exception):
    """Base exception for all beanJAMinBOT errors"""
    pass


# === Twitch API Exceptions ===

class TwitchAPIError(BotException):
    """Base class for Twitch API related errors"""
    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class TwitchAPIRequestError(TwitchAPIError):
    """HTTP request to Twitch API failed"""
    pass


class TwitchAPIResponseError(TwitchAPIError):
    """Twitch API returned unexpected response format"""
    pass


class TwitchResourceNotFoundError(TwitchAPIError):
    """Requested resource (user, channel, clip, etc.) not found"""
    pass


class TwitchRateLimitError(TwitchAPIError):
    """Rate limited by Twitch API"""
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


# === Authentication Exceptions ===

class AuthenticationError(BotException):
    """Base class for authentication failures"""
    pass


class TokenValidationError(AuthenticationError):
    """OAuth token validation failed"""
    pass


class TokenRefreshError(AuthenticationError):
    """Failed to refresh OAuth token"""
    pass


class TokenExchangeError(AuthenticationError):
    """Failed to exchange auth code for token"""
    pass


# === OBS Exceptions ===

class OBSError(BotException):
    """Base class for OBS-related errors"""
    pass


class OBSConnectionError(OBSError):
    """Failed to connect to OBS"""
    pass


class OBSSceneItemNotFoundError(OBSError):
    """Scene item not found in OBS"""
    def __init__(self, scene_name, source_name):
        super().__init__(f"Scene item '{source_name}' not found in '{scene_name}'")
        self.scene_name = scene_name
        self.source_name = source_name


# === Gambling Exceptions ===

class GambleError(BotException):
    """Base class for gambling errors"""
    pass


class InsufficientPointsError(GambleError):
    """User doesn't have enough points"""
    pass


class InvalidBetError(GambleError):
    """Bet amount is invalid"""
    pass


class BetExceedsBalanceError(GambleError):
    """Bet exceeds available balance"""
    pass


class NoDebtError(GambleError):
    """No debt to pay back"""
    pass


# === WebSocket/EventSub Exceptions ===

class WebSocketError(BotException):
    """Base class for WebSocket errors"""
    pass


class EventSubConnectionError(WebSocketError):
    """EventSub WebSocket connection failed"""
    pass


class EventSubSubscriptionError(WebSocketError):
    """Failed to create EventSub subscription"""
    pass