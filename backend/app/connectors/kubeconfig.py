import base64
from dataclasses import dataclass
from typing import Any

import yaml

MAX_KUBECONFIG_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class ParsedKubeconfig:
    server: str
    cluster_id: str
    context_name: str
    namespace: str
    verify_ssl: bool
    credentials: dict[str, str]


def parse_kubeconfig(content: str) -> ParsedKubeconfig:
    if not content.strip():
        raise ValueError("kubeconfig 文件为空")
    if len(content.encode()) > MAX_KUBECONFIG_BYTES:
        raise ValueError("kubeconfig 文件不能超过 1 MB")
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("kubeconfig YAML 格式无效") from exc
    if not isinstance(document, dict):
        raise ValueError("kubeconfig 顶层必须是对象")

    contexts = _named_items(document.get("contexts"), "contexts")
    clusters = _named_items(document.get("clusters"), "clusters")
    users = _named_items(document.get("users"), "users")
    context_name = str(document.get("current-context") or "").strip()
    if not context_name:
        context_name = next(iter(contexts), "")
    context = contexts.get(context_name)
    if context is None:
        raise ValueError("kubeconfig current-context 不存在")

    cluster_id = str(context.get("cluster") or "").strip()
    user_name = str(context.get("user") or "").strip()
    cluster = clusters.get(cluster_id)
    user = users.get(user_name)
    if cluster is None:
        raise ValueError("kubeconfig 当前 context 引用的 cluster 不存在")
    if user is None:
        raise ValueError("kubeconfig 当前 context 引用的 user 不存在")

    server = str(cluster.get("server") or "").strip().rstrip("/")
    if not server.startswith(("https://", "http://")):
        raise ValueError("kubeconfig cluster.server 必须是 HTTP(S) 地址")
    if cluster.get("certificate-authority"):
        raise ValueError("请使用包含 certificate-authority-data 的自包含 kubeconfig")
    if user.get("exec") or user.get("auth-provider"):
        auth_provider = user.get("auth-provider")
        token = (
            str(auth_provider.get("config", {}).get("access-token") or "").strip()
            if isinstance(auth_provider, dict)
            else ""
        )
        if not token:
            raise ValueError("暂不执行 kubeconfig exec/auth-provider，请导出自包含凭据")
    else:
        token = str(user.get("token") or "").strip()
    if user.get("tokenFile") or user.get("client-certificate") or user.get("client-key"):
        raise ValueError("请使用包含内嵌 token 或 client-*-data 的自包含 kubeconfig")

    credentials: dict[str, str] = {}
    if token:
        credentials["token"] = token.removeprefix("Bearer ").strip()
    ca_cert = _decode_data(cluster.get("certificate-authority-data"), "CA 证书")
    client_cert = _decode_data(user.get("client-certificate-data"), "客户端证书")
    client_key = _decode_data(user.get("client-key-data"), "客户端私钥")
    if ca_cert:
        credentials["ca_cert"] = ca_cert
    if client_cert or client_key:
        if not client_cert or not client_key:
            raise ValueError("kubeconfig 客户端证书和私钥必须同时存在")
        credentials["client_cert"] = client_cert
        credentials["client_key"] = client_key
    if not credentials.get("token") and not credentials.get("client_cert"):
        raise ValueError("kubeconfig 中未找到可用的 Token 或客户端证书")

    return ParsedKubeconfig(
        server=server,
        cluster_id=cluster_id or context_name,
        context_name=context_name,
        namespace=str(context.get("namespace") or "").strip(),
        verify_ssl=not bool(cluster.get("insecure-skip-tls-verify", False)),
        credentials=credentials,
    )


def _named_items(value: object, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"kubeconfig {field} 不能为空")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"kubeconfig {field} 条目无效")
        config = item.get(field[:-1])
        if not isinstance(config, dict):
            raise ValueError(f"kubeconfig {field} 条目缺少配置")
        result[item["name"]] = config
    return result


def _decode_data(value: object, label: str) -> str:
    if not value:
        return ""
    try:
        encoded = "".join(str(value).split())
        return base64.b64decode(encoded, validate=True).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"kubeconfig {label}不是有效的 Base64 文本") from exc
