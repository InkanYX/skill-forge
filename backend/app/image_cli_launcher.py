"""Child-process launcher. The vendored image_gen.py stays byte-for-byte unchanged."""
import json
import os
import runpy
import sys
from pathlib import Path
from urllib.parse import urlsplit
import httpx
import openai
from app.image_provider import pinned_url
from app.provider_diagnostics import provider_diagnostic, diagnostic_context

class PublicTransport(httpx.BaseTransport):
    def __init__(self): self.transport = httpx.HTTPTransport(retries=0)
    def handle_request(self, request):
        target, headers, extensions = pinned_url(str(request.url))
        outbound_headers = httpx.Headers(request.headers)
        outbound_headers.update(headers)
        outbound = httpx.Request(request.method, target, headers=outbound_headers, stream=request.stream,
                                 extensions={**request.extensions, **extensions})
        return self.transport.handle_request(outbound)
    def close(self): self.transport.close()


def main():
    output = Path(sys.argv[1]); cli = Path(__file__).resolve().parents[1] / 'vendor/imagegen/image_gen.py'
    original = openai.OpenAI
    openai.OpenAI = lambda: original(max_retries=0, timeout=httpx.Timeout(300, connect=8),
        http_client=httpx.Client(transport=PublicTransport(), follow_redirects=False, trust_env=False))
    mode = sys.argv[2]
    sys.argv = [str(cli), *sys.argv[2:]]
    try:
        runpy.run_path(str(cli), run_name='__main__')
    except BaseException as error:
        if isinstance(error, SystemExit) and error.code in (0, None): return
        secrets = (os.environ.get('OPENAI_API_KEY', ''),)
        path = urlsplit(os.environ.get('OPENAI_BASE_URL', '')).path.rstrip('/') + ('/images/edits' if mode == 'edit' else '/images/generations')
        if isinstance(error, openai.APIStatusError):
            diagnostic = provider_diagnostic(error.response, path, mode, secrets, 0)
            uncertain = error.status_code not in (400,401,403,404,405,422,429)
        else:
            diagnostic = diagnostic_context(path, mode, secrets, 0, error_type=type(error).__name__,
                message='执行中断或结果无法确认，请核对服务商记录。')
            uncertain = True
        output.write_text(json.dumps({'diagnostic': diagnostic, 'uncertain': uncertain}, ensure_ascii=False), encoding='utf-8')
        raise SystemExit(1) from None

if __name__ == '__main__': main()
