from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult, AuthStrategy
from app.modules.flows.auth.strategies.magic_link import MagicLinkStrategy
from app.modules.flows.auth.strategies.oauth import OAuthStrategy
from app.modules.flows.auth.strategies.otp import OTPStrategy
from app.modules.flows.auth.strategies.password_form import PasswordFormStrategy

__all__ = [
    "AuthAttempt",
    "AuthResult",
    "AuthStrategy",
    "PasswordFormStrategy",
    "MagicLinkStrategy",
    "OAuthStrategy",
    "OTPStrategy",
]
