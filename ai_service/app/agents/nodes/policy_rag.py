"""Policy RAG node: retrieval-augmented generation from bank policy documents."""
from __future__ import annotations

import logging
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState
from app.core.config import get_settings
from app.integrations.llm_factory import (
    create_llm,
    extract_message_text,
    sanitize_messages_for_llm,
)
from app.integrations.vectorstore_factory import get_vectorstore

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """
You are a banking policy assistant. Answer ONLY based on the provided policy documents.
If the information is not in the documents, say: "I couldn't find this information in the available policy documents."
Do NOT make up information or use general knowledge about banking.
Cite sources using [1], [2], etc. referencing the passage numbers.

Policy documents:
{passages}

Answer the user's question using ONLY the above documents. Cite each relevant passage.
"""


def policy_rag_node(state: GraphState, config: RunnableConfig = None) -> dict:
    """Retrieve relevant policy chunks and generate a grounded answer."""
    settings = get_settings()

    try:
        vectorstore = get_vectorstore(settings)

        # Retrieve top-k chunks
        query = state.get("user_message", "")
        docs = vectorstore.similarity_search_with_score(query, k=settings.rag_top_k)

        # Filter by active status and min score threshold
        relevant = []
        for doc, score in docs:
            meta = doc.metadata if hasattr(doc, "metadata") else {}
            if meta.get("active") is False:
                continue
            if score >= settings.rag_min_score:
                relevant.append((doc, score))

        citations = []
        if relevant:
            passages_text = ""
            for i, (doc, score) in enumerate(relevant, 1):
                meta = doc.metadata if hasattr(doc, "metadata") else {}
                doc_name = meta.get("doc_name", "Policy Doc")
                version = meta.get("version", "1")
                page = meta.get("page", "?")
                passage_label = f"[{i}] {doc_name} v{version} p{page}"
                content = doc.page_content if hasattr(doc, "page_content") else str(doc)
                passages_text += f"\n{passage_label}:\n{content}\n"
                citations.append(
                    {
                        "ref": i,
                        "doc_name": doc_name,
                        "version": version,
                        "page": meta.get("page"),
                        "section": meta.get("section"),
                    }
                )

            system = RAG_SYSTEM_PROMPT.format(passages=passages_text)
            llm = create_llm(settings)
            clean_messages = sanitize_messages_for_llm(
                state.get("messages", []),
                user_message=state.get("user_message", ""),
            )
            response = llm.invoke(
                [
                    SystemMessage(content=system),
                    *clean_messages,
                ]
            )
            response_text = extract_message_text(response.content if hasattr(response, "content") else response)
        else:
            response_text = "I couldn't find relevant information in the available policy documents."
            citations = []
    except Exception as exc:
        logger.warning("RAG node error: %s", exc)
        response_text = "I'm having trouble accessing policy documents right now. Please try again."
        citations = []

    return {
        "response": response_text,
        "citations": citations,
        "messages": [AIMessage(content=response_text)],
    }
