import pytest

from app.assignments import clean_speaker_name


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_names_stay_missing(raw):
    """交付集里 67% 没有姓名，这是正常情况而不是错误。"""
    assert clean_speaker_name(raw) is None


@pytest.mark.parametrize(
    "raw", ["PERSON", "PERSON1", "PERSON3", "All", "MODERATOR", "MEMBER-GIRL"]
)
def test_placeholders_are_dropped(raw):
    """占位符对认人没有帮助，展示它不如只展示静帧。"""
    assert clean_speaker_name(raw) is None


@pytest.mark.parametrize(
    "raw", ["Rachel", "CHANDLER", "Mr. Treeger", "Flight Attendant", "Dr. Zane"]
)
def test_real_names_and_role_labels_are_kept(raw):
    """角色描述不是脏值：「Flight Attendant」照样能告诉标注者该看谁。"""
    assert clean_speaker_name(raw) == raw


def test_windows_1252_apostrophe_is_repaired():
    """交付集里有一条 Richard\x92s Date，撇号被按 latin-1 读坏了。"""
    assert clean_speaker_name("Richard\x92s Date") == "Richard’s Date"
