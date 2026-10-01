"""
Memory: iOS stops a-Shell's WebAssembly engine if it uses too much. libjxl's
default turns its low-memory streaming mode off at effort 7 below quality ~70,
which took about 2.7 GB for a 24 MP photo; jxlbatch keeps streaming on.
"""

import re

import photo_helpers as ph
from PIL import Image

LIMIT = 1.5e9  # bytes; streaming needs about 0.5-0.8 GB for 24 MP


def test_24_mp_photo_at_low_quality(wasm, helpers, tmp_path, need_tools):
    tile = ph.scene(1428, 1071, seed=3)
    big = Image.new('RGB', (5712, 4284))
    for x in range(4):
        for y in range(4):
            big.paste(tile, (x * 1428, y * 1071))

    big.save(tmp_path / 'big.png')
    heic = tmp_path / 'big.heic'
    ph.run([helpers['make_photo'], tmp_path / 'big.png', heic], check=True)
    folder = tmp_path / 'job'
    ph.stage(folder, [heic])
    command = [p.replace('{dir}', str(folder)) for p in wasm.command]
    result = ph.run(
        ['/usr/bin/time', '-l', *command, '-q', '30', 'jxl_job.txt'],
        cwd=folder,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    peak = int(
        re.search(r'(\d+)\s+maximum resident set size', result.stderr).group(1)
    )
    assert peak < LIMIT, f'peak memory {peak / 1e9:.2f} GB'
