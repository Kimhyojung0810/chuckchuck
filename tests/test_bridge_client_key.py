"""
브리지 요청 제한이 **누구를** 세는가.

Cloudflare Tunnel 뒤에서는 모든 요청이 127.0.0.1 로 들어온다. 그대로 세면 심사위원
전원이 30회/분 한 통을 나눠 쓴다. 루프백 요청에 한해 CF-Connecting-IP 를 믿고,
바깥에서 온 요청의 같은 헤더는 위조일 수 있어 무시한다.
"""

from email.message import Message

from demo.bridge import Handler


def handler(addr: str, **headers) -> Handler:
    h = Handler.__new__(Handler)          # 소켓 없이 키 계산만 본다
    h.client_address = (addr, 12345)
    h.headers = Message()
    for k, v in headers.items():
        h.headers[k.replace("_", "-")] = v
    return h


def test_평소에는_소켓_주소가_키다():
    assert handler("10.0.0.7")._client_key() == "10.0.0.7"


def test_터널_뒤_루프백_요청은_CF_Connecting_IP_로_센다():
    assert handler("127.0.0.1", CF_Connecting_IP="203.0.113.9")._client_key() == "203.0.113.9"
    assert handler("::1", CF_Connecting_IP="203.0.113.9")._client_key() == "203.0.113.9"


def test_루프백인데_헤더가_없으면_루프백_그대로():
    assert handler("127.0.0.1")._client_key() == "127.0.0.1"


def test_바깥에서_온_요청의_헤더는_믿지_않는다():
    assert handler("10.0.0.7", CF_Connecting_IP="203.0.113.9")._client_key() == "10.0.0.7"
