"""Execute the selected image model while preserving provider-native PNG bytes."""
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image, ImageOps
from app.image_provider import GenerationError, MAX_IMAGE, MAX_PIXELS
from app.image_configurations import MODEL, RULES

BACKEND = Path(__file__).resolve().parents[1]
CLI = BACKEND / 'vendor/imagegen/image_gen.py'


def execute_cli(directory, profile, key, prompt, reference):
    directory.mkdir(parents=True, exist_ok=True)
    prompt_path, output, diagnostic_path = directory / 'prompt.txt', directory / 'result.png', directory / 'cli-diagnostic.json'
    if output.exists(): raise GenerationError('结果文件已存在，未重新调用接口，请检查已有结果。', True)
    prompt_path.write_text(prompt, encoding='utf-8')
    reference_path = directory / 'reference.png'
    if reference is not None and not reference_path.is_file():
        raise GenerationError('参考文件缺失，未调用编辑接口。')
    mode = 'edit' if reference is not None else 'generate'
    model = profile.get('model', MODEL)
    manifest = {'rules': {**RULES, 'model': model}, 'base_url': profile['base_url'], 'mode': mode, 'prompt_file': 'prompt.txt',
                'cli_sha256': hashlib.sha256(CLI.read_bytes()).hexdigest(),
                'references': [{'file':'reference.png', 'role': 'edit_target', 'sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest()}] if reference is not None else [],
                'review': {'status':'pending', 'method':'human'}, 'native_pixels': None}
    (directory / 'execution.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    command = [sys.executable, '-m', 'app.image_cli_launcher', str(diagnostic_path), mode,
               '--model', model, '--quality', 'high', '--size', 'auto', '--output-format', 'png', '--no-augment',
               '--n', '1', '--prompt-file', str(prompt_path), '--out', str(output)]
    if reference is not None: command.extend(['--image', str(reference_path)])
    env = dict(os.environ, OPENAI_BASE_URL=profile['base_url'], OPENAI_API_KEY=key, PYTHONUTF8='1')
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=330, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = -1
    if not output.is_file():
        if diagnostic_path.is_file():
            data = json.loads(diagnostic_path.read_text(encoding='utf-8'))
            data['diagnostic']['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            raise GenerationError('图片调用失败，请查看运行日志。', data['uncertain'], data['diagnostic'])
        raise GenerationError('执行超时或中断，结果待确认；未重复提交。', True)
    try:
        raw = output.read_bytes()
        if len(raw) > MAX_IMAGE or not raw.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError()
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS: raise ValueError()
            image.load(); pixels = list(image.size)
            preview = Image.new('RGB', image.size, 'white')
            if image.mode == 'RGBA': preview.paste(image, mask=image.getchannel('A'))
            else: preview.paste(image.convert('RGB'))
            preview.thumbnail((1024, 1024))
            preview.save(directory / 'preview.jpg', 'JPEG', quality=75, optimize=True)
    except (OSError, ValueError, Image.DecompressionBombError):
        raise GenerationError('已返回文件，但图片无效或超出限制；请核对服务商记录。', True) from None
    manifest.update(native_pixels=pixels, output_sha256=hashlib.sha256(raw).hexdigest(), elapsed_ms=int((time.monotonic()-started)*1000))
    (directory / 'execution.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest
