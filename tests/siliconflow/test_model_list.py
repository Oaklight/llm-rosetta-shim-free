"""SiliconFlow model-list transforms.

Ported from llm-rosetta tests/test_model_list_transforms.py
(TestSiliconFlowModelListTransform) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_model_list_transform


@pytest.fixture(autouse=True)
def _registered(register):
    register("siliconflow")


class TestSiliconFlowModelListTransform:
    """The SiliconFlow catalogue is typed, so each shim keeps its own slice.

    One playground response carries every endpoint (chat, embedding, image,
    video, speech, rerank) and marks entries ``status: normal`` or
    ``status: disable``.  A picker must see only the active entries of its own
    subtype, and the id is ``modelName``, the string the endpoint accepts.
    """

    ENTRIES = [
        {"modelName": "Qwen/Qwen3.6-27B", "status": "normal", "subType": "chat"},
        {
            "modelName": "deepseek-ai/DeepSeek-V4.1-Flash",
            "status": "normal",
            "subType": "chat",
        },
        {"modelName": "old/Retired-Chat", "status": "disable", "subType": "chat"},
        {"modelName": "BAAI/bge-m3", "status": "normal", "subType": "embedding"},
        {
            "modelName": "BAAI/bge-reranker-v2-m3",
            "status": "normal",
            "subType": "reranker",
        },
        {
            "modelName": "Wan-AI/Wan2.2-T2V-A14B",
            "status": "normal",
            "subType": "text-to-video",
        },
    ]

    def _ids(self, shim_name: str) -> list[str]:
        transform = get_model_list_transform(shim_name)
        assert transform is not None
        ids, upstream = transform(self.ENTRIES)
        assert upstream == {}
        return ids

    def test_chat_keeps_active_chat_models_only(self):
        assert self._ids("siliconflow--chat_completions") == [
            "Qwen/Qwen3.6-27B",
            "deepseek-ai/DeepSeek-V4.1-Flash",
        ]

    def test_embedding_keeps_active_embedding_models_only(self):
        assert self._ids("siliconflow--embedding") == ["BAAI/bge-m3"]

    def test_rerank_keeps_active_reranker_models_only(self):
        assert self._ids("siliconflow--rerank") == ["BAAI/bge-reranker-v2-m3"]

    def test_an_entry_without_a_name_is_dropped(self):
        transform = get_model_list_transform("siliconflow--chat_completions")
        assert transform is not None
        ids, _ = transform([{"status": "normal", "subType": "chat"}, self.ENTRIES[0]])
        assert ids == ["Qwen/Qwen3.6-27B"]
