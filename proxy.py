import os
import json
import traceback
import datetime
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI()

# Point proxy.py at the SGLang inference server (configured via SGLANG_URL / .env)
HEADROOM_URL = os.environ.get("SGLANG_URL") or os.environ.get("HEADROOM_URL") or "http://127.0.0.1:8000/v1/chat/completions"
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen3.6-27B-FP8")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "4000"))

# Global persistent HTTP client for connection pooling (HTTP Keep-Alive)
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(120.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=200)
)

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def convert_tools(anthropic_tools):
    if not anthropic_tools or not isinstance(anthropic_tools, list):
        return None
    openai_tools = []
    for tool in anthropic_tools:
        if isinstance(tool, dict):
            name = tool.get("name")
            if name and isinstance(name, str) and name.strip():
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
                    }
                })
    return openai_tools if openai_tools else None

def convert_messages(messages):
    openai_messages = []
    char_count = 0
    last_user_prompt = ""
    extra_system_prompts = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            if isinstance(content, str):
                extra_system_prompts.append(content)
                char_count += len(content)
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, str):
                        extra_system_prompts.append(b)
                        char_count += len(b)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        txt = b.get("text", "")
                        extra_system_prompts.append(txt)
                        char_count += len(txt)
            continue

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            char_count += len(content)
            if role == "user":
                last_user_prompt = content
            continue

        if isinstance(content, list):
            text_parts = []
            tool_calls = []
            tool_results = []

            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                    char_count += len(block)
                elif isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        txt = block.get("text", "")
                        text_parts.append(txt)
                        char_count += len(txt)
                    elif btype == "image":
                        source = block.get("source", {})
                        if isinstance(source, dict) and source.get("type") == "base64":
                            media_type = source.get("media_type", "image/png")
                            data = source.get("data", "")
                            text_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{data}"}
                            })
                            char_count += 200
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", f"call_{len(tool_calls)+1}"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False)
                            }
                        })
                        char_count += len(json.dumps(block.get("input", {}))) + len(block.get("name", ""))
                    elif btype == "tool_result":
                        res_content = block.get("content", "")
                        if isinstance(res_content, list):
                            res_parts = []
                            for b in res_content:
                                if isinstance(b, dict) and b.get("type") == "text":
                                    res_parts.append(b.get("text", ""))
                                elif isinstance(b, str):
                                    res_parts.append(b)
                                else:
                                    res_parts.append(str(b))
                            res_text = "\n".join(res_parts)
                        else:
                            res_text = str(res_content)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": res_text
                        })
                        char_count += len(res_text)

            if role == "assistant":
                oai_msg = {"role": "assistant"}
                oai_msg["content"] = text_parts if any(isinstance(tp, dict) for tp in text_parts) else ("\n".join(text_parts) if text_parts else "")
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                openai_messages.append(oai_msg)
            elif role == "user":
                if tool_results:
                    for tr in tool_results:
                        openai_messages.append(tr)
                if text_parts or not tool_results:
                    if any(isinstance(tp, dict) for tp in text_parts):
                        prompt_val = text_parts
                        last_user_prompt = "[Multimodal Content]"
                    else:
                        prompt_val = "\n".join(text_parts)
                        last_user_prompt = prompt_val
                    openai_messages.append({"role": "user", "content": prompt_val})

    return openai_messages, char_count, last_user_prompt, extra_system_prompts

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def catch_all(request: Request, path: str):
    ts = timestamp()
    print(f"[{ts}] --> Incoming Request: {request.method} /{path}")
    body = await request.body()
    try:
        body_json = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        body_json = {}

    if "count_tokens" in path:
        messages = body_json.get("messages", [])
        system = body_json.get("system", "")
        _, char_count, _, _ = convert_messages(messages)
        char_count += len(str(system))
        estimated_tokens = int((char_count / 3.5) * 1.15) + 50
        return JSONResponse({"input_tokens": max(estimated_tokens, 10)})

    if path in ["v1/messages", "messages"]:
        model = body_json.get("model", "qwen-27b")
        messages = body_json.get("messages", [])
        system = body_json.get("system", None)
        tools = body_json.get("tools", None)
        tool_choice = body_json.get("tool_choice", None)
        is_streaming = body_json.get("stream", True)

        conv_msgs, msg_char_count, last_user_prompt, extra_system_prompts = convert_messages(messages)

        system_blocks = []
        if system:
            if isinstance(system, list):
                system_blocks.append("\n".join([s.get("text", "") if isinstance(s, dict) else str(s) for s in system]))
            else:
                system_blocks.append(str(system))

        if extra_system_prompts:
            system_blocks.extend(extra_system_prompts)

        system_blocks.append("[Directive: Be direct, precise, and concise. When tool calls are needed, invoke tools immediately without excessive preamble or lengthy reasoning.]")

        unified_system_prompt = "\n\n".join(system_blocks)
        openai_messages = [{"role": "system", "content": unified_system_prompt}]
        openai_messages.extend(conv_msgs)
        char_count += len(unified_system_prompt) + msg_char_count

        openai_tools = convert_tools(tools)
        estimated_input_tokens = int((char_count / 3.5) * 1.15) + 50

        prompt_snippet = last_user_prompt.strip().replace("\n", " ")
        if len(prompt_snippet) > 120:
            prompt_snippet = prompt_snippet[:120] + "..."
        print(f"[{ts}]     Prompt: \"{prompt_snippet}\" -> Forwarding to SGLang Server ({HEADROOM_URL})")

        payload = {
            "model": MODEL_NAME,
            "messages": openai_messages,
            "max_tokens": body_json.get("max_tokens", 4096),
            "stream": is_streaming,
            "temperature": body_json.get("temperature") if body_json.get("temperature") is not None else 0.2,
        }

        if openai_tools:
            payload["tools"] = openai_tools

        if tool_choice and isinstance(tool_choice, dict) and openai_tools:
            tc_type = tool_choice.get("type")
            if tc_type in ["auto", "any"]:
                payload["tool_choice"] = "auto"
            elif tc_type == "tool" and "name" in tool_choice:
                payload["tool_choice"] = {"type": "function", "function": {"name": tool_choice["name"]}}

        if "stop_sequences" in body_json and body_json["stop_sequences"]:
            payload["stop"] = body_json["stop_sequences"]
        if "top_p" in body_json and body_json["top_p"] is not None:
            payload["top_p"] = body_json["top_p"]

        # Handle non-streaming requests forwarded to Headroom Proxy
        if not is_streaming:
            try:
                res = await http_client.post(HEADROOM_URL, json=payload, timeout=120.0)
                if res.status_code != 200:
                    return JSONResponse({"error": {"type": "api_error", "message": res.text}}, status_code=res.status_code)

                oai_res = res.json()
                choices = oai_res.get("choices", [])
                if not choices:
                    return JSONResponse({"error": {"type": "api_error", "message": "No choices in OpenAI response"}}, status_code=500)

                choice = choices[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "stop")

                content_blocks = []
                text_content = message.get("content") or message.get("reasoning_content")
                if text_content:
                    content_blocks.append({"type": "text", "text": text_content})

                tool_calls = message.get("tool_calls", [])
                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except Exception:
                            args = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", f"toolu_{int(datetime.datetime.now().timestamp())}"),
                            "name": func.get("name", ""),
                            "input": args
                        })

                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})

                if tool_calls or finish_reason in ["tool_calls", "function_call"]:
                    stop_reason = "tool_use"
                elif finish_reason == "length":
                    stop_reason = "max_tokens"
                else:
                    stop_reason = "end_turn"

                claude_response = {
                    "id": oai_res.get("id", "msg_1"),
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": content_blocks,
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": estimated_input_tokens,
                        "output_tokens": oai_res.get("usage", {}).get("completion_tokens", len(text_content or ""))
                    }
                }
                return JSONResponse(claude_response)
            except Exception as e:
                print(f"[{timestamp()}] !!! Error forwarding to Headroom Proxy: {e}")
                traceback.print_exc()
                return JSONResponse({"error": {"type": "api_error", "message": str(e)}}, status_code=500)

        # Handle streaming requests forwarded to Headroom Proxy
        async def event_generator():
            full_response_chunks = []
            current_block_index = 0
            text_block_open = False
            text_block_index = None
            active_tool_calls = {}
            final_stop_reason = "end_turn"

            try:
                async with http_client.stream("POST", HEADROOM_URL, json=payload) as response:
                    print(f"[{timestamp()}] <-- SGLang Connection Status: {response.status_code}")
                    if response.status_code != 200:
                        error_bytes = await response.aread()
                        err_msg = error_bytes.decode('utf-8', errors='replace')
                        print(f"[{timestamp()}] !!! SGLang Error ({response.status_code}): {err_msg}")
                        err_block = {"type": "text", "text": f"\n[SGLang Error {response.status_code}: {err_msg}]\n"}
                        yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_err', 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': 'end_turn', 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
                        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': err_block})}\n\n"
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                        yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
                        return

                    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': estimated_input_tokens, 'output_tokens': 0}}})}\n\n"

                    async for line in response.aiter_lines():
                        if await request.is_disconnected():
                            print(f"[{timestamp()}] Client disconnected, terminating stream.")
                            break

                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    choice = choices[0]
                                    delta = choice.get("delta", {})
                                    finish_reason = choice.get("finish_reason")

                                    if finish_reason == "length":
                                        final_stop_reason = "max_tokens"
                                    elif finish_reason in ["tool_calls", "function_call"]:
                                        final_stop_reason = "tool_use"

                                    content_delta = delta.get("content") or delta.get("reasoning_content") or ""
                                    tool_calls_delta = delta.get("tool_calls", [])

                                    # 1. Handle tool call deltas from OpenAI stream
                                    if tool_calls_delta:
                                        final_stop_reason = "tool_use"
                                        if text_block_open:
                                            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"
                                            text_block_open = False

                                        for tc in tool_calls_delta:
                                            tc_idx = tc.get("index", 0)
                                            tc_id = tc.get("id")
                                            func = tc.get("function", {})
                                            func_name = func.get("name")
                                            func_args = func.get("arguments", "")

                                            if tc_idx not in active_tool_calls:
                                                tool_block_index = current_block_index
                                                current_block_index += 1
                                                tool_id = tc_id or f"toolu_{int(datetime.datetime.now().timestamp())}_{tc_idx}"
                                                tool_name = func_name or "tool"
                                                active_tool_calls[tc_idx] = {
                                                    "index": tool_block_index,
                                                    "id": tool_id,
                                                    "name": tool_name
                                                }
                                                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': tool_block_index, 'content_block': {'type': 'tool_use', 'id': tool_id, 'name': tool_name, 'input': {}}})}\n\n"

                                            if func_args:
                                                tool_block_index = active_tool_calls[tc_idx]["index"]
                                                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': tool_block_index, 'delta': {'type': 'input_json_delta', 'partial_json': func_args}})}\n\n"

                                    # 2. Handle text content deltas
                                    if content_delta:
                                        full_response_chunks.append(content_delta)
                                        if not text_block_open and not active_tool_calls:
                                            text_block_index = current_block_index
                                            current_block_index += 1
                                            text_block_open = True
                                            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': text_block_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

                                        if text_block_open:
                                            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': content_delta}})}\n\n"

                            except Exception:
                                pass

                    # Close open blocks
                    if text_block_open:
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"

                    for tc_idx, info in active_tool_calls.items():
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': info['index']})}\n\n"

                    if active_tool_calls:
                        final_stop_reason = "tool_use"

                    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': final_stop_reason, 'stop_sequence': None}, 'usage': {'output_tokens': len(full_response_chunks)}})}\n\n"
                    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

                    full_text = "".join(full_response_chunks).strip().replace("\n", " ")
                    if len(full_text) > 160:
                        full_text = full_text[:160] + "..."
                    print(f"[{timestamp()}] <-- Headroom Response Output: \"{full_text}\" (Tools Called: {len(active_tool_calls)})")

            except Exception as e:
                print(f"[{timestamp()}] !!! Error connecting to Headroom Proxy: {e}")
                traceback.print_exc()

        sse_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PROXY_PORT)
