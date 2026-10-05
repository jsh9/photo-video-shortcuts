"""
jxlbatch's command line and batch behavior, for every build (SIMD and scalar
WebAssembly, native).
"""

import re
import zlib

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


def with_cicp(png, primaries, transfer):
    """Adds a cICP chunk (CICP color: primaries, transfer, RGB, full range)."""
    data = png.read_bytes()
    chunk = b'cICP' + bytes([primaries, transfer, 0, 1])
    crc = zlib.crc32(chunk).to_bytes(4, 'big')
    png.write_bytes(
        data[:33] + (4).to_bytes(4, 'big') + chunk + crc + data[33:]
    )


@pytest.mark.parametrize(
    ('mode', 'primaries', 'pq'),
    [
        ('RGB', 9, True),  # Rec. 2100 PQ: stored as PQ
        ('RGB', 5, False),  # primaries jxlbatch doesn't map: stored as sRGB
        ('L', 9, False),  # gray: stored as sRGB
    ],
)
def test_pq_png_brightness(encoder, tmp_path, mode, primaries, pq):
    # A PQ image's intensity target is PQ's peak, 10,000 nits; one stored as
    # sRGB keeps the default, like any SDR image.
    Image.new(mode, (16, 16), 128).save(tmp_path / 'pq.png')
    with_cicp(tmp_path / 'pq.png', primaries, 16)
    ph.stage(tmp_path, [tmp_path / 'pq.png'])
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    jxl = tmp_path / 'jxl_out_1.jxl'
    info = ph.run(['jxlinfo', '-v', jxl], check=True).stdout.lower()
    assert (
        'pq transfer function' in info or 'transfer function: pq' in info
    ) == pq
    assert ph.jxl_intensity_target(jxl) == (10000 if pq else None)


def test_mac_flag_drops_the_share_sheet_hint(encoder, photos, tmp_path):
    # The Mac shortcuts hand over the library's files as they are, so an
    # iPhone JPEG is the original: no "Send As" hint with --mac.
    ph.stage(tmp_path, list(photos.values()))
    result = encoder.run(
        ['--mac', '-q', '83', '-e', '7', 'jxl_job.txt'], tmp_path
    )
    assert result.returncode == 0, result.stdout
    assert 'Note: Photos sent' not in result.stdout
    assert 'send as Current' not in result.stdout


def has_threads(encoder, folder):
    """
    Whether the build has threads (native, macOS): -j and -t then take effect.
    The WebAssembly builds accept them and convert one photo at a time.
    """
    help_text = encoder.run(['--help'], folder).stdout
    return 'this build has no threads' not in help_text


@pytest.mark.parametrize(
    ('option', 'value'),
    [('-j', '65'), ('-j', 'x'), ('-t', '-1'), ('-t', '1.5')],
)
def test_rejects_bad_jobs_and_threads(encoder, tmp_path, option, value):
    result = encoder.run([option, value, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert f'{option} must be between 0 and 64' in result.stdout


def stage_with_failures(folder, photos):
    """
    Every test photo staged, with a GIF (unsupported) and a missing file among
    them, so that a batch has failures to report in order too.
    """
    staged = ph.stage(folder, list(photos.values()))
    Image.new('RGB', (8, 8)).save(folder / 'jxl_in_2.orig', 'GIF')
    (folder / f'jxl_in_{len(staged) - 1}.orig').unlink()
    return len(staged) - 2


def header_and_body(output):
    """
    jxlbatch's first paragraph (one line, however it was wrapped) and the rest
    without its timings, which differ from run to run.
    """
    header, body = output.split('\n\n', 1)
    body = re.sub(r'(, [0-9.]+ s|in [0-9]+ s)(?=\n|$)', '', body)
    return ' '.join(header.split()), body


def test_parallel_batch_matches_sequential(encoder, photos, tmp_path):
    # Several photos at a time (-j) give the same files, the same
    # jxl_done.txt and the same output as one at a time: finished photos
    # join the batch in job order, each printed as one block.
    runs = {}
    for label, args in (('one', []), ('three', ['-j', '3'])):
        folder = tmp_path / label
        converted = stage_with_failures(folder, photos)
        result = encoder.run([*args, 'jxl_job.txt'], folder)
        assert result.returncode == 0, result.stdout
        header, body = header_and_body(result.stdout)
        runs[label] = {
            'header': header,
            'body': body,
            'done': (folder / 'jxl_done.txt').read_text(),
            'files': {
                p.name: p.read_bytes() for p in folder.glob('jxl_out_*.jxl')
            },
        }
        assert len(runs[label]['files']) == converted
        assert f'Done: {converted} of {converted + 2} converted' in body
        assert '2 failed; see the messages above.' in body

    one, three = runs['one'], runs['three']
    for key in ('body', 'done', 'files'):
        assert one[key] == three[key], key

    # The header says so, in the builds with threads.
    assert 'at a time' not in one['header']
    assert (', 3 at a time (' in three['header']) == has_threads(
        encoder, tmp_path
    )


def test_one_thread(encoder, tmp_path):
    # -j 1 -t 1 (the Mac shortcuts' "One core"): one photo at a time on one
    # thread, said in the header by the builds with threads.
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    result = encoder.run(['-j', '1', '-t', '1', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    header, body = header_and_body(result.stdout)
    assert header.endswith(', 1 thread') == has_threads(encoder, tmp_path)
    assert 'Done: 1 of 1 converted' in body


def test_auto_jobs_never_exceed_the_photos(encoder, tmp_path):
    # -j 0 (the Mac shortcuts' "All cores") picks from the cores, but never
    # more workers than photos: one photo is converted by one.
    ph.stage(tmp_path, [small_photo(tmp_path / 'a.png')])
    result = encoder.run(['-j', '0', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'at a time' not in result.stdout
    assert 'Done: 1 of 1 converted' in result.stdout
