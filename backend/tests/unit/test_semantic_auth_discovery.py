import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.engine.ai.schemas import AuthEntranceSemanticResult, AuthFormSemanticResult
from app.engine.browser.auth import (
    find_auth_entrance_semantically,
    find_auth_inputs_semantically,
    perform_login,
)
from app.engine.exploration.explorer import ExplorationEngine


@pytest.mark.asyncio
async def test_find_auth_entrance_semantically_keyword_fallback():
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    candidates = [
        {"index": 0, "tagName": "a", "text": "About Us", "href": "/about", "role": "", "ariaLabel": ""},
        {"index": 1, "tagName": "button", "text": "Get Started", "href": "", "role": "button", "ariaLabel": ""},
        {"index": 2, "tagName": "a", "text": "Pricing", "href": "/pricing", "role": "", "ariaLabel": ""},
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc = MagicMock()
    mock_loc.is_visible = AsyncMock(return_value=True)
    mock_loc.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_loc))

    success = await find_auth_entrance_semantically(mock_page, provider=None, is_signup=True)
    assert success is True
    mock_loc.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_auth_entrance_semantically_with_ai_provider():
    mock_page = MagicMock()
    mock_page.url = "https://custom-app.com"
    candidates = [
        {"index": 0, "tagName": "button", "text": "Take a Quiz", "href": "", "role": "button", "ariaLabel": ""},
        {"index": 1, "tagName": "button", "text": "Explore", "href": "", "role": "button", "ariaLabel": ""},
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc = MagicMock()
    mock_loc.is_visible = AsyncMock(return_value=True)
    mock_loc.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_loc))

    mock_provider = MagicMock()
    mock_provider.generate_structured = AsyncMock(
        return_value=AuthEntranceSemanticResult(
            entrance_index=0,
            confidence=0.9,
            reasoning="Take a Quiz enters user flow",
        )
    )

    success = await find_auth_entrance_semantically(mock_page, provider=mock_provider, is_signup=True)
    assert success is True
    mock_page.locator.assert_called_with('[data-kova-entrance-candidate="0"]')


@pytest.mark.asyncio
async def test_find_auth_inputs_semantically_layout_and_at_placeholder():
    mock_page = MagicMock()
    mock_page.frames = []
    candidates = [
        {
            "index": 0,
            "tagName": "input",
            "type": "text",
            "name": "custom_field_1",
            "id": "inp-1",
            "placeholder": "name@domain.com",
            "ariaLabel": "",
            "labelText": "",
            "role": "",
            "text": "",
        },
        {
            "index": 1,
            "tagName": "input",
            "type": "text",
            "name": "secret_key",
            "id": "inp-2",
            "placeholder": "Enter secret code",
            "ariaLabel": "",
            "labelText": "Security PIN",
            "role": "",
            "text": "",
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc_email = MagicMock()
    mock_loc_pwd = MagicMock()

    def locator_side_effect(selector):
        if "0" in selector:
            return MagicMock(first=mock_loc_email)
        return MagicMock(first=mock_loc_pwd)

    mock_page.locator = MagicMock(side_effect=locator_side_effect)

    name_loc, email_loc, pwd_loc, scope = await find_auth_inputs_semantically(mock_page, provider=None, is_signup=False)
    assert email_loc is not None
    assert pwd_loc is not None


@pytest.mark.asyncio
async def test_explorer_has_visible_auth_inputs_in_modal():
    explorer = ExplorationEngine(exploration_id="test-id", url="https://example.com")
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.frames = []

    mock_dialog_loc = MagicMock()
    mock_dialog_loc.is_visible = AsyncMock(return_value=True)

    def locator_side_effect(selector):
        loc = MagicMock()
        if "dialog" in selector or "form" in selector:
            loc.first.is_visible = AsyncMock(return_value=True)
        else:
            loc.first.is_visible = AsyncMock(return_value=False)
        return loc

    mock_page.locator = MagicMock(side_effect=locator_side_effect)

    has_inputs = await explorer._has_visible_auth_inputs(mock_page)
    assert has_inputs is True


@pytest.mark.asyncio
async def test_perform_login_switches_to_signup_view_when_requested_on_signin():
    mock_page = MagicMock()
    mock_page.url = "https://example.com/signin"
    mock_page.frames = []

    opened_signup = []

    async def mock_open_auth(page, is_signup=False, provider=None, event_recorder=None):
        if is_signup:
            opened_signup.append(True)
            mock_page.url = "https://example.com/signup"
            return True
        return False

    with patch("app.engine.browser.auth.open_auth_view_if_needed", side_effect=mock_open_auth), \
         patch("app.engine.browser.auth.find_auth_inputs_across_frames", return_value=(None, None, None, mock_page)):
        await perform_login(mock_page, "new@example.com", "SecretPass1!", is_signup=True)
        assert True in opened_signup


def test_classify_auth_page_all_kinds():
    from app.engine.browser.auth import AuthSignalBundle, classify_auth_page

    # 1. Login
    b_login = AuthSignalBundle(
        url_path_is_auth=True,
        visible_password_input_count=1,
        visible_email_input_count=1,
        visible_otp_input_count=0,
        has_remember_me_checkbox=True,
        has_forgot_password_link=True,
        submit_button_texts=["Sign In"],
        url="https://example.com/app/login",
    )
    res_login = classify_auth_page(b_login)
    assert res_login.kind == "login"
    assert res_login.confidence >= 0.9

    # 2. Signup
    b_signup = AuthSignalBundle(
        url_path_is_auth=True,
        visible_password_input_count=1,
        visible_email_input_count=1,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        submit_button_texts=["Create Account"],
        url="https://example.com/register",
    )
    res_signup = classify_auth_page(b_signup)
    assert res_signup.kind == "signup"
    assert res_signup.confidence >= 0.9

    # 3. Magic link
    b_magic = AuthSignalBundle(
        url_path_is_auth=True,
        visible_password_input_count=0,
        visible_email_input_count=1,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        magic_link_form_markers=["Send magic link"],
        submit_button_texts=["Send Link"],
        url="https://example.com/auth",
    )
    res_magic = classify_auth_page(b_magic)
    assert res_magic.kind == "magic_link"
    assert res_magic.confidence >= 0.9

    # 4. OAuth redirect
    b_oauth = AuthSignalBundle(
        url_path_is_auth=False,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        oauth_button_texts=["Continue with Google", "Sign in with GitHub"],
        url="https://example.com/oauth/authorize",
    )
    res_oauth = classify_auth_page(b_oauth)
    assert res_oauth.kind == "oauth_redirect"
    assert res_oauth.confidence >= 0.9

    # 5. OTP verification
    b_otp = AuthSignalBundle(
        url_path_is_auth=False,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=1,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        submit_button_texts=["Verify Code"],
        url="https://example.com/verify-otp",
    )
    res_otp = classify_auth_page(b_otp)
    assert res_otp.kind == "otp_verification"
    assert res_otp.confidence >= 0.9

    # 6. Not auth
    b_not_auth = AuthSignalBundle(
        url_path_is_auth=False,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        submit_button_texts=["Save Settings"],
        url="https://example.com/dashboard/analytics",
    )
    res_not_auth = classify_auth_page(b_not_auth)
    assert res_not_auth.kind == "not_auth"
    assert res_not_auth.confidence >= 0.9

    # 7. Ambiguous (URL is auth but 0 inputs visible yet)
    b_ambiguous = AuthSignalBundle(
        url_path_is_auth=True,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        url="https://example.com/login",
    )
    res_ambiguous = classify_auth_page(b_ambiguous)
    assert res_ambiguous.kind == "ambiguous"
    assert res_ambiguous.confidence < 0.5


def test_classify_auth_page_dom_signal_wins_over_ambiguous_url():
    from app.engine.browser.auth import AuthSignalBundle, classify_auth_page

    bundle = AuthSignalBundle(
        url_path_is_auth=False,
        visible_password_input_count=1,
        visible_email_input_count=1,
        visible_otp_input_count=0,
        has_remember_me_checkbox=True,
        has_forgot_password_link=True,
        submit_button_texts=["Enter"],
        url="https://example.com/products/view/123",
    )
    res = classify_auth_page(bundle)
    assert res.kind == "login"
    assert res.confidence >= 0.9


def test_classify_auth_page_loading_ambiguous_state():
    from app.engine.browser.auth import AuthSignalBundle, classify_auth_page

    bundle = AuthSignalBundle(
        url_path_is_auth=True,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
        url="https://example.com/accounts/login",
    )
    res = classify_auth_page(bundle)
    assert res.kind == "ambiguous"
    assert res.confidence < 0.5


def test_levenshtein_distance_matching():
    from app.engine.browser.auth import _levenshtein_distance

    assert _levenshtein_distance("Sign in", "sign in") == 0
    assert _levenshtein_distance("Sign-in", "sign in") == 1
    assert _levenshtein_distance("SIGN IN", "sign in") == 0
    assert _levenshtein_distance("Log in", "log in") == 0
    assert _levenshtein_distance("Login", "log in") == 1

