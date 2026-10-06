"""
The user's own videos (tests/samples/compress-videos/*.mov|mp4, not committed:
they may carry locations) through the shortcut's script with each codec, at
720p and a fast preset, checked as test_conversion.py checks the test videos:
every Apple key, the rotation, HDR, Dolby Vision, the sound. A slo-mo or
spatial sample is expected to be skipped.
"""

from pathlib import Path

import pytest
import video_helpers as vh

SAMPLES = sorted(
    p
    for p in (vh.HERE.parent / 'samples' / 'compress-videos').glob('*')
    if p.suffix.lower() in ('.mov', '.mp4', '.m4v')
)
SETTINGS = {
    'h265': {'Codec': 'h265', 'Preset': 'fast', 'Tune': 'none', 'RF': '28'},
    'av1': {'Codec': 'av1', 'Preset': '5', 'Tune': '', 'RF': '40'},
}


@pytest.mark.parametrize('codec', ['h265', 'av1'])
@pytest.mark.parametrize('video', SAMPLES, ids=lambda p: p.name)
def test_sample(tmp_path, actions, tools, helpers, video, codec):
    mac = vh.Mac(tmp_path, actions, tools)
    mac.export(video, video.name)
    lines = mac.convert(
        f'ID|{video.name}', Size='720p', Audio='128', **SETTINGS[codec]
    )
    if 'Skipped ' in mac.skipped:
        assert lines == []
        assert 'slo-mo' in mac.skipped or 'spatial' in mac.skipped, mac.log
        return

    assert len(lines) == 1, mac.log
    copy = Path(lines[0].split('|')[0])
    assert '!' not in mac.log, mac.log
    original = vh.avmeta(helpers['avmeta'], video)
    result = vh.avmeta(helpers['avmeta'], copy)
    assert result['playable'] is True
    assert result['metadata'] == original['metadata']
    o_video = next(t for t in original['tracks'] if t['mediaType'] == 'vide')
    c_video = next(t for t in result['tracks'] if t['mediaType'] == 'vide')
    assert c_video.get('metadata', {}) == o_video.get('metadata', {})
    assert c_video['rotation'] == o_video['rotation']
    assert c_video['BitsPerComponent'] == 10
    assert c_video['hdr'] == o_video['hdr']
    if 'dvvC' in o_video.get('atoms', []):
        assert 'dvvC' in c_video['atoms']
        assert 'Dolby Vision kept' in mac.log

    assert max(c_video['naturalSize']) <= 1280
    sounds = [t for t in result['tracks'] if t['mediaType'] == 'soun']
    assert [t['codec'] for t in sounds] == ['opus'][: len(sounds)]
