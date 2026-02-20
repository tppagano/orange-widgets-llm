"""
Chatbot Widgets
===============

Orange widgets for chatbot functionality.

"""

# Widget category metadata
NAME = "Chatbot"
ID = "orangecontrib.chatbot.widgets"
DESCRIPTION = "Chatbot widgets with RAG capabilities"
PRIORITY = 100
ICON = "icons/chatbot.svg"
BACKGROUND = "#FFF8DC"

# Widget list - will be discovered automatically
WIDGETS = [
    {
        "name": "RAG Vectorizer",
        "description": "Vectorize documents for RAG",
        "icon": "icons/rag.svg",
        "priority": 90,
    },
    {
        "name": "LLM Config",
        "description": "Configure LLM and parameters",
        "icon": "icons/llm.svg",
        "priority": 95,
    },
    {
        "name": "Chatbot",
        "description": "Interactive chatbot interface",
        "icon": "icons/chatbot.svg",
        "priority": 100,
    }
]
