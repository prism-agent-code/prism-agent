from typing import List
from sentence_transformers import SentenceTransformer
import torch
from src.agent import runtime_config

rc = runtime_config.RuntimeConfig()


class STEmbeddings:
    def __init__(self, model_name: str, device: str = "cpu", trust_remote_code: bool = True,
                 local_files_only: bool = True, query_prompt: str | None = None):
        self.model = SentenceTransformer(
            model_name,
            device=device,
            trust_remote_code=trust_remote_code,
            local_files_only=local_files_only,
            model_kwargs={"torch_dtype": torch.bfloat16},  # 或 torch.float16
        )
        self.model.max_seq_length = 512
        self.local_files_only = local_files_only
        self.query_prompt = query_prompt

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embs = self.model.encode(
            texts,
            normalize_embeddings=True,  # 检索更稳
            show_progress_bar=True,
            device="cuda:7",
            batch_size=32
        )
        return [e.tolist() for e in embs]

    def embed_query(self, text: str) -> List[float]:
        emb = self.model.encode(
            [text],
            prompt=self.query_prompt,  # 关键：只对 query 侧加
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )[0]
        return emb.tolist()
