"""
새 데이터 계약을 contracts.py에 넣을 때 참고하는 템플릿입니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class MyItem:
    slide_no: int
    label: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MyItem":
        return cls(
            slide_no=int(d["slide_no"]),
            label=d.get("label", ""),
            score=float(d.get("score", 0.0)),
        )


@dataclass
class MyOut:
    """F-XX 산출물. 다음 모듈의 입력이 된다."""

    file_name: str
    items: list[MyItem] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "model": self.model,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MyOut":
        return cls(
            file_name=d["file_name"],
            model=d.get("model", ""),
            items=[MyItem.from_dict(i) for i in d.get("items", [])],
        )


# contracts.py 의 ChuckchuckError 를 상속해 모듈 전용 에러를 둔다.
# class MyError(ChuckchuckError): ...
