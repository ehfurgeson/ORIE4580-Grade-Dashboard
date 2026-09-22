from pathlib import Path


def test_course_root_redirect_uses_trusted_remote_user_server_side():
    config = Path("apache/course-root-redirect.conf").read_text()
    assert 'LocationMatch "^/orie4580_fa26/?$"' in config
    assert "AuthType shibboleth" in config
    assert "ShibRequestSetting requireSession 1" in config
    assert "<RequireAll>" in config
    assert "Require valid-user" in config
    assert 'Require expr "%{REMOTE_USER} =~ m#^[a-z]{2,3}[0-9]+$#"' in config
    assert "RewriteCond %{LA-U:REMOTE_USER} ^([a-z]{2,3}[0-9]+)$" in config
    assert "RewriteRule ^/orie4580_fa26/?$ /orie4580_fa26/students/%1/ [R=302,L,NE]" in config


def test_redirect_is_temporary_and_has_no_untrusted_identity_input():
    config = Path("apache/course-root-redirect.conf").read_text()
    assert "R=301" not in config
    assert "QUERY_STRING" not in config
    assert "HTTP_COOKIE" not in config
    assert "HTTP:" not in config
    assert "THE_REQUEST" not in config


def test_obsolete_netid_landing_page_is_removed():
    assert not Path("deployment/simple-index.html").exists()
