import pytest

from app.services.youtube_url import InvalidYouTubeUrl, parse_youtube_url

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url,kind",
    [
        (f"https://www.youtube.com/watch?v={VID}", "video"),
        (f"https://youtu.be/{VID}", "video"),
        (f"https://youtu.be/{VID}?si=tracking123&t=42", "video"),
        (f"https://www.youtube.com/live/{VID}", "live"),
        (f"https://www.youtube.com/live/{VID}?feature=share", "live"),
        (f"https://www.youtube.com/watch?v={VID}&feature=share", "video"),
        (f"https://www.youtube.com/watch?v={VID}&list=PLabcdefghijkl&index=3", "video"),
        (f"https://www.youtube.com/watch?list=PLabc&v={VID}", "video"),
        (f"https://m.youtube.com/watch?v={VID}", "video"),
        (f"https://www.youtube.com/shorts/{VID}", "short"),
        (f"https://youtube.com/shorts/{VID}?feature=share", "short"),
        (f"https://www.youtube.com/embed/{VID}", "video"),
        (f"https://www.youtube-nocookie.com/embed/{VID}", "video"),
        (f"https://music.youtube.com/watch?v={VID}", "video"),
        (f"www.youtube.com/watch?v={VID}", "video"),
        (f"  https://www.youtube.com/watch?v={VID}  ", "video"),
        (f"HTTPS://WWW.YOUTUBE.COM/watch?v={VID}", "video"),
        (f"https://www.youtube.com:443/watch?v={VID}", "video"),
    ],
)
def test_valid_urls(url, kind):
    parsed = parse_youtube_url(url)
    assert parsed.video_id == VID
    assert parsed.url_kind == kind
    assert parsed.canonical_url == f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not a url",
        "https://vimeo.com/123456",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQextra",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
        "https://www.youtube.com/playlist?list=PL123",
        "https://youtu.be/",
        "https://evil.com/?u=https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com@evil.com/watch?v=dQw4w9WgXcQ",
        "https://user:pass@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8080/watch?v=dQw4w9WgXcQ",
        "javascript:alert(1)//www.youtube.com/watch?v=dQw4w9WgXcQ",
        "file:///etc/passwd",
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "http://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "http://169.254.169.254/latest/meta-data",
        "https://www.youtube.com/watch?v=dQw4w9WgX<Q",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ\nHost: evil",
        "https://www.youtube.com/shorts/../../etc",
        "https://www.youtube.com/" + "a" * 3000,
    ],
)
def test_invalid_or_malicious_urls(url):
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url(url)


def test_non_string_rejected():
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url(None)  # type: ignore[arg-type]
