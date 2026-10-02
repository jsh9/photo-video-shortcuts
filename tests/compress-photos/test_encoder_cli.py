"""
jxlbatch's command line and batch behavior, for every build (SIMD and scalar
WebAssembly, native).
"""

import photo_helpers as ph
import pytest
from PIL import Image


def small_photo(path):
    ph.scene(64, 48).save(path)
    return path


def test_version_matches_version_file(encoder, tmp_path):
    result = encoder.run(['--version'], tmp_path)
    version = (ph.TOOL / 'VERSION').read_text().strip()
    assert result.returncode == 0
    assert f'jxlbatch {version} ' in result.stdout


def test_selftest_passes(encoder, tmp_path):
    result = encoder.run(['--selftest'], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Self-test passed' in result.stdout
    # including the HDR code: a gain map photo with Apple's HDR profile
    assert 'HDR decoding:' in result.stdout
    assert "Apple's HDR profile kept" in result.stdout


@pytest.mark.parametrize('quality', ['abc', '0', '101', '-5'])
def test_rejects_bad_quality(encoder, tmp_path, quality):
    result = encoder.run(['-q', quality, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert 'quality must be between 1 and 100' in result.stdout


@pytest.mark.parametrize('effort', ['0', '11', 'x'])
def test_rejects_bad_effort(encoder, tmp_path, effort):
    result = encoder.run(['-e', effort, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert 'effort must be between 1 and 10' in result.stdout


def test_accepts_decimal_comma(encoder, tmp_path):
    # Shortcuts can format numbers with a comma in some locales.
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    result = encoder.run(['-q', '83,5', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'quality 83.5' in result.stdout


def test_missing_job_file(encoder, tmp_path):
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 1
    assert 'cannot find jxl_job.txt' in result.stdout


def test_retry_skips_a_started_batch(encoder, tmp_path):
    # The shortcut's retry line, after jxlbatch already ran.
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    (tmp_path / 'jxl_started').touch()
    result = encoder.run(['--retry', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'jxlbatch: 1 photo' not in result.stdout
    assert not (tmp_path / 'jxl_done.txt').exists()


def test_retry_runs_a_batch_not_started(encoder, tmp_path):
    # The shortcut's retry line, after a-Shell couldn't start jxlbatch.
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    result = encoder.run(['--retry', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'Done: 1 of 1 converted' in result.stdout


def test_batch_continues_after_failed_photos(encoder, tmp_path):
    # 1: a PNG, 2: a GIF (unsupported), 3: missing, 4: a JPEG
    ph.scene(64, 48).save(tmp_path / 'jxl_in_1.orig', 'PNG')
    Image.new('RGB', (8, 8)).save(tmp_path / 'jxl_in_2.orig', 'GIF')
    ph.scene(64, 48).save(tmp_path / 'jxl_in_4.orig', 'JPEG')
    (tmp_path / 'jxl_job.txt').write_text('1|a.png\n2|b.gif\n3|c.png\n4|d.jpg')
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'unsupported format' in result.stdout
    assert 'cannot read jxl_in_3.orig' in result.stdout
    assert 'Done: 2 of 4 converted' in result.stdout
    assert (tmp_path / 'jxl_started').exists()
    # The format the shortcuts read: "file|index|delete or keep|name", one
    # per line ("keep": the JXL lacks the original's HDR).
    assert (tmp_path / 'jxl_done.txt').read_text() == (
        'jxl_out_1.jxl|1|delete|a.jxl\njxl_out_4.jxl|4|delete|d.jxl'
    )


def test_nothing_converted(encoder, tmp_path):
    gif = tmp_path / 'b.gif'
    Image.new('RGB', (8, 8)).save(gif)
    ph.stage(tmp_path, [gif])
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 1
    assert not (tmp_path / 'jxl_done.txt').exists()
    # It did start, so the shortcut's retry must not run it again.
    assert (tmp_path / 'jxl_started').exists()


def test_saved_names_are_safe(encoder, tmp_path):
    small_photo(tmp_path / 'x.png')
    (tmp_path / 'jxl_in_1.orig').write_bytes((tmp_path / 'x.png').read_bytes())
    # "|" separates fields in jxl_done.txt, so it can't stay in a name.
    (tmp_path / 'jxl_job.txt').write_text('1|My|Photo: 1/2.HEIC')
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert (tmp_path / 'jxl_done.txt').read_text() == (
        'jxl_out_1.jxl|1|delete|My_Photo_ 1_2.jxl'
    )


def test_sdr_option(encoder, tmp_path):
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    result = encoder.run(['--sdr', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'Done: 1 of 1 converted' in result.stdout
