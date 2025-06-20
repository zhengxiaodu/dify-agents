from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import requests
import json
import sys
from typing import Any, Optional, Dict
# Initialize FastMCP server
mcp = FastMCP("weather")
from requests.exceptions import RequestException, Timeout, ConnectionError

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"


async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get('event', 'Unknown')}
Area: {props.get('areaDesc', 'Unknown')}
Severity: {props.get('severity', 'Unknown')}
Description: {props.get('description', 'No description available')}
Instructions: {props.get('instruction', 'No specific instructions provided')}
"""

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period['name']}:
Temperature: {period['temperature']}°{period['temperatureUnit']}
Wind: {period['windSpeed']} {period['windDirection']}
Forecast: {period['detailedForecast']}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)


@mcp.tool()
async def send_dify_chat_request(
    query: str,
    inputs: Optional[Dict[str, Any]] = None,
    user_id: str = "user123",
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    response_mode: str = "streaming",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    向Dify API询问历史信息并处理响应

    Args:
        query: 用户的提问内容
        inputs: 允许传入App定义的各变量值, 默认为空字典
        user_id: 用户标识，用于定义终端用户身份，默认为"user123"
        api_key: Dify API密钥，如不提供则使用默认值
        api_url: Dify API URL，如不提供则使用默认值
        response_mode: 响应模式，可选"streaming"或"blocking"，默认为"streaming"
        timeout: 请求超时时间（秒），默认为30

    Returns:
        Dict: 包含AI回答、使用情况等信息的字典
    """
    # 设置API密钥和URL
    if api_key is None:
        api_key = "app-fTXTTY3Tfd7oxznnAKZgR6YF"  # 使用默认API密钥

    if api_url is None:
        api_url = "https://api.dify.ai/v1/workflows/run"  # 使用默认URL

    # 打印调试信息
    print(f"向Dify API发送请求: 查询={query}, 用户={user_id}")

    # 设置请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 设置请求体
    if inputs is None:
        inputs = {'query':query}

    data = {
        "inputs": inputs,
        "response_mode": response_mode,
        "user": user_id
    }

    result = {
        "success": False,
        "answer": "",
        "usage_info": None,
        "error": None,
        "workflow_info": {}
    }

    try:
        # 发送请求，添加超时设置
        print(f"发送请求到 {api_url}")
        response = requests.post(api_url, headers=headers, json=data, stream=True, timeout=timeout)

        # 处理流式响应，但只在全部接收后才输出
        if response.status_code == 200:
            full_answer = ""
            usage_info = None
            workflow_info = {}
            error_occurred = False

            try:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data_str = line[6:]  # 去掉 'data: ' 前缀
                            try:
                                data_json = json.loads(data_str)
                                event_type = data_json.get("event")

                                # 处理不同类型的事件
                                if event_type == "message":
                                    full_answer += data_json.get("answer", "")

                                # 在消息结束时获取使用信息
                                elif event_type == "message_end":
                                    if "metadata" in data_json:
                                        usage_info = data_json.get("metadata", {}).get("usage")

                                # 处理错误事件
                                elif event_type == "error":
                                    error_occurred = True
                                    error_message = data_json.get("error", "未知错误")
                                    print(f"API错误: {error_message}")
                                    result["error"] = f"API错误: {error_message}"
                                    break

                                # 处理工作流事件
                                elif event_type == "workflow_started":
                                    workflow_info["id"] = data_json.get("workflow_run_id")
                                    print(f"工作流开始: {workflow_info['id']}")

                                elif event_type == "workflow_finished":
                                    status = data_json.get("data", {}).get("status")
                                    print(f"工作流完成: {status}")
                                    workflow_info["status"] = status

                                    # 检查工作流是否失败
                                    if status == "failed":
                                        error_msg = data_json.get("data", {}).get("error", "未知错误")
                                        print(f"工作流执行失败: {error_msg}")
                                        result["error"] = f"工作流执行失败: {error_msg}"
                                    full_answer += data_json.get("data", {}).get("outputs", "").get('text', "")

                                # 处理节点事件
                                elif event_type in ["node_started", "node_finished"]:
                                    node_id = data_json.get("data", {}).get("node_id")
                                    node_status = data_json.get("data", {}).get("status", "running")

                                    if event_type == "node_finished" and node_status == "failed":
                                        error_msg = data_json.get("data", {}).get("error", "未知错误")
                                        print(f"节点 {node_id} 执行失败: {error_msg}")
                                        result["error"] = f"节点 {node_id} 执行失败: {error_msg}"

                                # 处理文件消息
                                elif event_type == "message_file":
                                    file_id = data_json.get("id")
                                    file_type = data_json.get("type")
                                    file_url = data_json.get("url")
                                    print(f"收到文件: ID={file_id}, 类型={file_type}, URL={file_url}")
                                    if "files" not in result:
                                        result["files"] = []
                                    result["files"].append({
                                        "id": file_id,
                                        "type": file_type,
                                        "url": file_url
                                    })

                                # 处理TTS（文字转语音）消息
                                elif event_type in ["tts_message", "tts_message_end"]:
                                    print(f"收到TTS事件: {event_type}")

                                # 处理消息替换事件
                                elif event_type == "message_replace":
                                    full_answer = data_json.get("answer", "")
                                    print("消息内容被替换（可能是由于内容审查）")

                            except json.JSONDecodeError as e:
                                error_message = f"JSON解析错误: {e}"
                                print(error_message)
                                result["error"] = error_message
                            except Exception as e:
                                error_message = f"处理消息时出错: {e}"
                                print(error_message)
                                result["error"] = error_message
            except Exception as e:
                error_message = f"读取响应流时出错: {e}"
                print(error_message)
                result["error"] = error_message

            # 全部收集完后，只有在没有错误时才输出结果
            if not error_occurred:
                print("AI回答:", full_answer)

                # 如果需要，还可以输出使用情况
                if usage_info:
                    print("\n使用情况:")
                    print(f"提示令牌: {usage_info.get('prompt_tokens', 'N/A')}")
                    print(f"完成令牌: {usage_info.get('completion_tokens', 'N/A')}")
                    print(f"总令牌: {usage_info.get('total_tokens', 'N/A')}")

            # 设置返回结果
            result["success"] = not error_occurred
            result["answer"] = full_answer
            result["usage_info"] = usage_info
            result["workflow_info"] = workflow_info

        else:
            # 处理HTTP错误代码
            error_message = "未知错误"
            try:
                error_data = response.json()
                error_message = error_data.get("error", {}).get("message", str(error_data))
            except (json.JSONDecodeError, ValueError, KeyError):
                error_message = response.text

            print(f"请求失败，状态码: {response.status_code}")
            print(f"错误信息: {error_message}")

            result["error"] = f"请求失败，状态码: {response.status_code}, 错误信息: {error_message}"

            # 处理常见的HTTP错误
            if response.status_code == 401:
                print("认证失败: 请检查您的API密钥是否正确")
                result["error_type"] = "authentication_error"
            elif response.status_code == 403:
                print("权限不足: 您的API密钥没有足够的权限执行此操作")
                result["error_type"] = "permission_error"
            elif response.status_code == 404:
                print("资源不存在: 请检查API端点URL是否正确")
                result["error_type"] = "not_found_error"
            elif response.status_code == 429:
                print("请求过多: 已超过API速率限制，请稍后再试")
                result["error_type"] = "rate_limit_error"
            elif 500 <= response.status_code < 600:
                print("服务器错误: 服务器端发生错误，请稍后再试")
                result["error_type"] = "server_error"

    except Timeout:
        error_message = "请求超时: 服务器没有在预期的时间内响应"
        print(error_message)
        result["error"] = error_message
        result["error_type"] = "timeout_error"
    except ConnectionError:
        error_message = "连接错误: 无法连接到服务器，请检查网络连接和服务器状态"
        print(error_message)
        result["error"] = error_message
        result["error_type"] = "connection_error"
    except RequestException as e:
        error_message = f"请求异常: {e}"
        print(error_message)
        result["error"] = error_message
        result["error_type"] = "request_error"
    except Exception as e:
        error_message = f"发生未预期的错误: {e}"
        print(error_message)
        result["error"] = error_message
        result["error_type"] = "unexpected_error"

    return result

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='sse')