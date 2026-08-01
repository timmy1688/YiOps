import base64

import pytest

from app.connectors.kubeconfig import parse_kubeconfig


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _config(*, user: str, cluster: str, context: str = "production") -> str:
    return f"""
apiVersion: v1
kind: Config
current-context: {context}
clusters:
  - name: prod-cluster
    cluster:
{cluster}
users:
  - name: yiops-reader
    user:
{user}
contexts:
  - name: production
    context:
      cluster: prod-cluster
      user: yiops-reader
      namespace: checkout
"""


def test_parse_token_kubeconfig() -> None:
    content = _config(
        cluster=(
            "      server: https://kubernetes.example.com:6443\n"
            f"      certificate-authority-data: {_encoded('test-ca')}"
        ),
        user="      token: Bearer read-only-token",
    )

    parsed = parse_kubeconfig(content)

    assert parsed.server == "https://kubernetes.example.com:6443"
    assert parsed.cluster_id == "prod-cluster"
    assert parsed.context_name == "production"
    assert parsed.namespace == "checkout"
    assert parsed.verify_ssl is True
    assert parsed.credentials == {"token": "read-only-token", "ca_cert": "test-ca"}


def test_parse_client_certificate_and_insecure_cluster() -> None:
    content = _config(
        cluster=(
            "      server: https://10.0.0.1:6443\n"
            "      insecure-skip-tls-verify: true"
        ),
        user=(
            f"      client-certificate-data: {_encoded('client-certificate')}\n"
            f"      client-key-data: {_encoded('client-key')}"
        ),
    )

    parsed = parse_kubeconfig(content)

    assert parsed.verify_ssl is False
    assert parsed.credentials == {
        "client_cert": "client-certificate",
        "client_key": "client-key",
    }


def test_first_context_is_used_when_current_context_is_missing() -> None:
    content = _config(
        context="",
        cluster="      server: http://kubernetes.default.svc",
        user="      token: test-token",
    )
    content = content.replace("current-context: \n", "")

    parsed = parse_kubeconfig(content)

    assert parsed.context_name == "production"


@pytest.mark.parametrize(
    ("user", "message"),
    [
        ("      exec:\n        command: kubectl", "暂不执行 kubeconfig exec/auth-provider"),
        ("      tokenFile: /var/run/token", "请使用包含内嵌 token"),
    ],
)
def test_external_credential_sources_are_rejected(user: str, message: str) -> None:
    content = _config(
        cluster="      server: https://kubernetes.example.com",
        user=user,
    )

    with pytest.raises(ValueError, match=message):
        parse_kubeconfig(content)


def test_path_based_certificate_authority_is_rejected() -> None:
    content = _config(
        cluster=(
            "      server: https://kubernetes.example.com\n"
            "      certificate-authority: /home/user/.kube/ca.crt"
        ),
        user="      token: test-token",
    )

    with pytest.raises(ValueError, match="certificate-authority-data"):
        parse_kubeconfig(content)
