"""OpenAI Chat Completions requests for tools that only speak that format (Cherry Studio's "OpenAI" type and
the like), carried out as Claude Messages requests with the official SDK (gateway.py), and the answers turned
back into Chat Completions responses and stream chunks.

What has no counterpart is left out on purpose: temperature, top_p and the like (the Messages API takes the
defaults since API version 2026-10-21), n > 1, logprobs and audio. Forcing a tool call ("required" or a named
function) becomes "auto": the current models refuse forced tool use.
"""
import base64
import binascii
import json
import re
import time
import uuid

DEFAULT_MAX_TOKENS = 16000
EFFORTS = {'minimal': 'low', 'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'xhigh', 'max': 'max'}
FINISH = {'end_turn': 'stop', 'stop_sequence': 'stop', 'pause_turn': 'stop', 'max_tokens': 'length',
          'model_context_window_exceeded': 'length', 'tool_use': 'tool_calls', 'refusal': 'content_filter'}
DATA_URL = re.compile(r'data:([\w.+-]+/[\w.+-]+)(?:;[\w.+-]+=[^;,]*)*;base64,(.*)', re.S)
IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')


class RequestError(ValueError):
    """The request cannot become a Messages request: a 400 with this message."""


def text_of(content) -> str:
    """Plain text from a message's content: a string, or a list of parts of which the text ones count."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if not isinstance(part, dict):
                raise RequestError('消息内容的格式不正确。')
            value = part.get('refusal') if part.get('type') == 'refusal' else part.get('text')
            if part.get('type') in ('text', 'input_text', 'output_text', 'refusal') and isinstance(value, str) and value:
                texts.append(value)
        return '\n'.join(texts)
    raise RequestError('消息内容的格式不正确。')


def data_url(url: str):
    match = DATA_URL.fullmatch(url.strip())
    if not match:
        return None
    media_type, data = match.group(1).lower(), re.sub(r'\s', '', match.group(2))
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RequestError('附件的 base64 数据不完整。') from exc
    return media_type, data


def user_blocks(content) -> list:
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}] if content else []
    if not isinstance(content, list):
        raise RequestError('用户消息的内容格式不正确。')
    blocks = []
    for part in content:
        if not isinstance(part, dict):
            raise RequestError('用户消息的内容格式不正确。')
        kind = part.get('type')
        if kind in ('text', 'input_text'):
            if isinstance(part.get('text'), str) and part['text']:
                blocks.append({'type': 'text', 'text': part['text']})
        elif kind == 'image_url':
            image = part.get('image_url')
            url = image.get('url') if isinstance(image, dict) else image
            if not isinstance(url, str) or not url:
                raise RequestError('图片地址为空。')
            inline = data_url(url)
            if inline:
                if inline[0] not in IMAGE_TYPES:
                    raise RequestError(f'Claude 不支持这种图片格式：{inline[0]}（可用 JPEG、PNG、GIF、WebP）。')
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': inline[0], 'data': inline[1]}})
            elif url.startswith(('https://', 'http://')):
                blocks.append({'type': 'image', 'source': {'type': 'url', 'url': url}})
            else:
                raise RequestError('图片需要是网址或 base64 数据。')
        elif kind == 'file':
            file = part.get('file') if isinstance(part.get('file'), dict) else {}
            inline = data_url(file.get('file_data', '')) if isinstance(file.get('file_data'), str) else None
            if not inline:
                raise RequestError('文件需要以 base64 数据附在请求里。')
            media_type, data = inline
            if media_type == 'application/pdf':
                document = {'type': 'document', 'source': {'type': 'base64', 'media_type': media_type, 'data': data}}
            elif media_type.startswith('text/'):
                document = {'type': 'document', 'source': {'type': 'text', 'media_type': 'text/plain',
                                                           'data': base64.b64decode(data).decode('utf-8', errors='replace')}}
            else:
                raise RequestError(f'Claude 不能直接读取这种文件：{media_type}（可用 PDF 和纯文本）。')
            if isinstance(file.get('filename'), str) and file['filename']:
                document['title'] = file['filename'][:200]
            blocks.append(document)
        elif kind in ('input_audio', 'audio'):
            raise RequestError('Claude 不接受音频输入。')
        else:
            raise RequestError(f'不支持的消息内容类型：{kind}')
    return blocks


def assistant_blocks(message: dict) -> list:
    text = text_of(message.get('content'))
    blocks = [{'type': 'text', 'text': text}] if text else []
    calls = message.get('tool_calls') or []
    if not isinstance(calls, list):
        raise RequestError('tool_calls 的格式不正确。')
    for call in calls:
        function = call.get('function') if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get('name'), str) or not isinstance(call.get('id'), str):
            raise RequestError('tool_calls 的格式不正确。')
        arguments = function.get('arguments') or '{}'
        try:
            values = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError as exc:
            raise RequestError(f'工具 {function["name"]} 的调用参数不是有效的 JSON。') from exc
        if not isinstance(values, dict):
            raise RequestError(f'工具 {function["name"]} 的调用参数应是 JSON 对象。')
        blocks.append({'type': 'tool_use', 'id': call['id'], 'name': function['name'], 'input': values})
    return blocks


def tool_result(message: dict) -> dict:
    if not isinstance(message.get('tool_call_id'), str):
        raise RequestError('工具结果缺少 tool_call_id。')
    return {'type': 'tool_result', 'tool_use_id': message['tool_call_id'], 'content': text_of(message.get('content'))}


def to_anthropic(body: dict, model: str, max_output: int | None = None) -> dict:
    """Messages request parameters for a Chat Completions request body; model is the one the gateway chose."""
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages:
        raise RequestError('messages 不能为空。')
    if body.get('n') not in (None, 1):
        raise RequestError('每次只能生成一个回答（n 只能是 1）。')
    system, turns = [], []

    def add(role, blocks):
        if not blocks:
            return
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'].extend(blocks)  # tool results of parallel calls belong in one user turn
        else:
            turns.append({'role': role, 'content': list(blocks)})

    for message in messages:
        if not isinstance(message, dict):
            raise RequestError('messages 的格式不正确。')
        role = message.get('role')
        if role in ('system', 'developer'):
            text = text_of(message.get('content'))
            if text:
                system.append(text)
        elif role == 'user':
            add('user', user_blocks(message.get('content')))
        elif role == 'assistant':
            add('assistant', assistant_blocks(message))
        elif role == 'tool':
            add('user', [tool_result(message)])
        else:
            raise RequestError(f'不支持的消息角色：{role}')
    if not turns:
        raise RequestError('请求里没有可发送的消息。')

    limit = body.get('max_completion_tokens', body.get('max_tokens'))
    if limit is None:
        limit = DEFAULT_MAX_TOKENS
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise RequestError('max_tokens 应是正整数。')
    if max_output:
        limit = min(limit, max_output)
    params = {'model': model, 'max_tokens': limit, 'messages': turns}
    if system:
        params['system'] = '\n\n'.join(system)

    stop = body.get('stop')
    if isinstance(stop, str) and stop:
        params['stop_sequences'] = [stop]
    elif isinstance(stop, list) and stop:
        params['stop_sequences'] = [item for item in stop if isinstance(item, str) and item][:8]

    tools = body.get('tools')
    if tools:
        if not isinstance(tools, list):
            raise RequestError('tools 的格式不正确。')
        converted = []
        for tool in tools:
            function = tool.get('function') if isinstance(tool, dict) and tool.get('type', 'function') == 'function' else None
            if not isinstance(function, dict) or not isinstance(function.get('name'), str):
                raise RequestError('只支持 function 类型的工具。')
            schema = function.get('parameters') if isinstance(function.get('parameters'), dict) else {'type': 'object', 'properties': {}}
            entry = {'name': function['name'], 'input_schema': schema}
            if isinstance(function.get('description'), str) and function['description']:
                entry['description'] = function['description']
            converted.append(entry)
        params['tools'] = converted
        choice = body.get('tool_choice')
        if choice == 'none':
            params['tool_choice'] = {'type': 'none'}
        elif body.get('parallel_tool_calls') is False:
            params['tool_choice'] = {'type': 'auto', 'disable_parallel_tool_use': True}

    output_config = {}
    effort = body.get('reasoning_effort')
    if isinstance(effort, str) and effort in EFFORTS:
        output_config['effort'] = EFFORTS[effort]
    response_format = body.get('response_format')
    if isinstance(response_format, dict) and response_format.get('type') == 'json_schema':
        schema = (response_format.get('json_schema') or {}).get('schema')
        if not isinstance(schema, dict):
            raise RequestError('response_format 缺少 JSON Schema。')
        output_config['format'] = {'type': 'json_schema', 'schema': schema}
    if output_config:
        params['output_config'] = output_config
    return params


def usage(values) -> dict:
    """Chat Completions usage from Messages usage (an SDK object or a dict of token counts)."""
    get = values.get if isinstance(values, dict) else lambda name, default=None: getattr(values, name, default)
    read, written = get('cache_read_input_tokens') or 0, get('cache_creation_input_tokens') or 0
    prompt = (get('input_tokens') or 0) + read + written
    completion = get('output_tokens') or 0
    return {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': prompt + completion,
            'prompt_tokens_details': {'cached_tokens': read}}


def to_openai(message, model: str) -> dict:
    """A Chat Completions response for a finished Messages response (an SDK Message)."""
    text = ''.join(block.text for block in message.content if block.type == 'text')
    reasoning = ''.join(getattr(block, 'thinking', '') or '' for block in message.content if block.type == 'thinking')
    calls = [{'id': block.id, 'type': 'function', 'function': {'name': block.name, 'arguments': json.dumps(block.input, ensure_ascii=False)}}
             for block in message.content if block.type == 'tool_use']
    answer = {'role': 'assistant', 'content': text or (None if calls else ''), 'refusal': None}
    if calls:
        answer['tool_calls'] = calls
    if reasoning:
        answer['reasoning_content'] = reasoning
    return {'id': 'chatcmpl-' + message.id, 'object': 'chat.completion', 'created': int(time.time()), 'model': model,
            'choices': [{'index': 0, 'message': answer, 'finish_reason': FINISH.get(message.stop_reason, 'stop'), 'logprobs': None}],
            'usage': usage(message.usage)}


class Chunks:
    """Chat Completions stream chunks from Messages stream events, one event at a time."""

    def __init__(self, model: str):
        self.id = 'chatcmpl-' + uuid.uuid4().hex
        self.created = int(time.time())
        self.model = model
        self.tools = {}  # content block index -> tool call index
        self.tokens = {'input_tokens': 0, 'output_tokens': 0, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}

    def chunk(self, delta: dict, finish=None) -> dict:
        return {'id': self.id, 'object': 'chat.completion.chunk', 'created': self.created, 'model': self.model,
                'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish, 'logprobs': None}]}

    def count(self, values):
        for name in self.tokens:
            value = getattr(values, name, None)
            if value is not None:
                self.tokens[name] = value

    def feed(self, event) -> list:
        kind = event.type
        if kind == 'message_start':
            self.id = 'chatcmpl-' + event.message.id
            self.count(event.message.usage)
            return [self.chunk({'role': 'assistant', 'content': ''})]
        if kind == 'content_block_start' and event.content_block.type == 'tool_use':
            index = self.tools[event.index] = len(self.tools)
            block = event.content_block
            return [self.chunk({'tool_calls': [{'index': index, 'id': block.id, 'type': 'function', 'function': {'name': block.name, 'arguments': ''}}]})]
        if kind == 'content_block_delta':
            delta = event.delta
            if delta.type == 'text_delta' and delta.text:
                return [self.chunk({'content': delta.text})]
            if delta.type == 'thinking_delta' and delta.thinking:
                return [self.chunk({'reasoning_content': delta.thinking})]
            if delta.type == 'input_json_delta' and event.index in self.tools and delta.partial_json:
                return [self.chunk({'tool_calls': [{'index': self.tools[event.index], 'function': {'arguments': delta.partial_json}}]})]
            return []
        if kind == 'message_delta':
            self.count(event.usage)
            return [self.chunk({}, FINISH.get(event.delta.stop_reason, 'stop'))]
        return []

    def usage_chunk(self) -> dict:
        return {'id': self.id, 'object': 'chat.completion.chunk', 'created': self.created, 'model': self.model,
                'choices': [], 'usage': usage(self.tokens)}


def sse(data) -> bytes:
    return b'data: ' + (data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()) + b'\n\n'


def error_body(message: str, kind: str = 'invalid_request_error', code=None) -> dict:
    return {'error': {'message': message, 'type': kind, 'param': None, 'code': code}}
