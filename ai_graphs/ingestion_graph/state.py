from typing import TypedDict, NotRequired

from ai_graphs.ingestion_graph.models import Notice, NoticeTarget, Source

class IngestionState(TypedDict):
    sources: NotRequired[tuple[Source, ...]]
    notice_targets: NotRequired[tuple[NoticeTarget, ...]]
    notices: NotRequired[tuple[Notice, ...]]
    saved_count: NotRequired[int]
    errors: NotRequired[tuple[str, ...]]
