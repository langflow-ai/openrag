from services.models_service import _watsonx_rate_limited

REAL_403 = (
    '{"errors":[{"code":"user_authorization_failed","message":"Failed to find the '
    "IBMid-6950006MXS member in project_id 1f17210f-84ff-4865-b94f-d0a80ad0f62a "
    '{\\"code\\":429,\\"error\\":\\"Too Many Requests\\"}"}]}'
)


def test_throttling_hidden_inside_a_403_is_detected():
    assert _watsonx_rate_limited([("text chat", 403, REAL_403)]) is True


def test_plain_429_is_detected():
    assert _watsonx_rate_limited([("embedding", 429, "")]) is True


def test_a_real_authorization_failure_is_not_called_throttling():
    body = '{"errors":[{"code":"user_authorization_failed","message":"not a member"}]}'
    assert _watsonx_rate_limited([("text chat", 403, body)]) is False


def test_no_failures_is_not_throttling():
    assert _watsonx_rate_limited([]) is False
