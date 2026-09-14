"""只监听 loopback 的本地诊断页面，不依赖外部网站。"""
import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

logger = logging.getLogger('app.browser.site')
HTML = '''<!doctype html><title>Browser fixture</title>
<div id="safe"><h1>Local fixture</h1><input id="name"><input type="password" value="fixture-private">
<button id="go" onclick="document.querySelector('#result').textContent='clicked'">Go</button>
<p id="result">ready</p></div>
<form onsubmit="event.preventDefault();window.submissions=(window.submissions||0)+1">
<input id="field"><button id="submit">Submit</button></form>
<script>setTimeout(()=>{const p=document.createElement('p');p.id='later';p.textContent='later';document.body.append(p)},100)</script>'''


@asynccontextmanager
async def browser_site(requests=None):
    handlers = set()
    async def handle(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            raw = await reader.readuntil(b'\r\n\r\n')
            path = urlsplit(raw.split(b' ')[1].decode()).path
            if requests is not None:
                requests.append((raw.split(b' ')[0].decode(), path))
            if path == '/delay':
                await asyncio.sleep(2)
            status = '500 Internal Server Error' if path == '/error' else '200 OK'
            extra = ''
            if path == '/redirect':
                status, extra = '302 Found', 'Location: /simple\r\n'
            if path == '/qq/redirect-blocked':
                status, extra = '302 Found', 'Location: http://169.254.169.254/latest/meta-data/\r\n'
            if path.startswith('/qq/'):
                from app.tools.qq_web_fixture import fixture_html
                body = fixture_html(path, raw.decode()).encode()
            else:
                body = HTML.encode()
            writer.write(f'HTTP/1.1 {status}\r\n{extra}Content-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            logger.debug('fixture_connection_closed', extra={'event':'fixture_connection_closed'})
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                logger.debug('fixture_connection_closed', extra={'event':'fixture_connection_closed'})
            handlers.discard(task)
    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    try:
        yield f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
    finally:
        server.close()
        await server.wait_closed()
        pending = list(handlers)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
