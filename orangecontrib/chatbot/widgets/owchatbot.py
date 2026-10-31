# BUILD: CHATBOT_MELHORIAS_1_3_4_5_CORRETO_20260810
"""
Orange3 Chatbot Widget
======================

A chatbot widget with RAG (Retrieval-Augmented Generation) capabilities.

"""

import sys
import os
import csv
from typing import List, Optional

from AnyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QScrollArea, QTextEdit, QWidget,
    QMessageBox, QInputDialog
)
from AnyQt.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from AnyQt.QtGui import QIcon, QPixmap, QPainter
from AnyQt.QtSvg import QSvgRenderer

from Orange.data import Table, StringVariable, Domain
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output

# RAG backend will be initialized only when documents are provided
try:
    from orangecontrib.chatbot.rag_backend import stream_chain_with_history
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

CSV_FILE = "conversas.csv"
LLM_DEFAULT = "llama3.1:8b"

CSV_FIELDS = [
    "mensagem_id",
    "chat_id",
    "chat_title",
    "mensagem_usuario",
    "resposta_bot",
    "llm_usada",
    "avaliacao",
    "fontes_rag",
]


# ====================
# Helper Classes
# ====================

class SpinnerLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)

        self.angle = 0
        self.renderer = QSvgRenderer(bytearray("""
        <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
          <circle cx="50" cy="50" r="45"
            stroke="#888"
            stroke-width="10"
            fill="none"
            stroke-dasharray="210"
            stroke-dashoffset="60"
            stroke-linecap="round"/>
        </svg>
        """, encoding="utf-8"))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(50)

    def rotate(self):
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)

        painter = QPainter(pix)
        painter.translate(12, 12)
        painter.rotate(self.angle)
        painter.translate(-12, -12)
        self.renderer.render(painter)
        painter.end()

        self.setPixmap(pix)
        self.angle = (self.angle + 15) % 360


class TypingLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__("Pensando")
        self.base = "Pensando"
        self.dots = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(500)

    def animate(self):
        self.dots = (self.dots + 1) % 4
        self.setText(self.base + "." * self.dots)


class LLMWorker(QThread):
    partial = pyqtSignal(str)
    finished = pyqtSignal(str)
    sources = pyqtSignal(list)

    def __init__(self, llm_config, chat_history, prompt, use_mock=False):
        super().__init__()
        self.llm_config = llm_config
        self.chat_history = chat_history
        self.prompt = prompt
        self.use_mock = use_mock

    def _create_llm(self):
        """Create the LLM configured in the OWLLM widget."""
        model_config = self.llm_config or {}

        if model_config.get("model_type") == "ollama":
            from langchain_ollama import OllamaLLM

            return OllamaLLM(
                model=model_config["model"],
                temperature=model_config.get("temperature", 0.7),
                num_ctx=model_config.get("max_tokens", 4096),
            )

        raise ValueError(
            f"Unknown model type: {model_config.get('model_type', 'none')}"
        )

    def _get_prompt_instruction(self):
        """Read the manual instruction received from the Prompt widget."""
        model_config = self.llm_config or {}
        prompt_config = model_config.get("prompt_config") or {}

        instruction = (
            model_config.get("prompt_text")
            or model_config.get("prompt_instruction")
            or prompt_config.get("prompt_text")
            or prompt_config.get("prompt_instruction")
            or "Responda de forma clara e objetiva."
        )

        return str(instruction).strip()

    def _retrieve_sources(self, retriever):
        """Retrieve document/chunk metadata for the current RAG query."""
        try:
            if hasattr(retriever, "invoke"):
                docs = retriever.invoke(self.prompt)
            elif hasattr(retriever, "get_relevant_documents"):
                docs = retriever.get_relevant_documents(self.prompt)
            else:
                return []
        except Exception:
            return []

        sources = []
        seen = set()

        for doc in docs or []:
            metadata = getattr(doc, "metadata", {}) or {}
            label = (
                metadata.get("doc_label")
                or metadata.get("source")
                or metadata.get("doc_id")
                or "Documento"
            )
            chunk = metadata.get("chunk")
            key = (str(label), str(chunk) if chunk is not None else "")

            if key in seen:
                continue

            seen.add(key)
            sources.append({"label": str(label), "chunk": chunk})

        return sources

    def _format_history(self):
        """Format the current conversation history for non-RAG responses."""
        if not self.chat_history:
            return "Nenhuma conversa anterior."

        lines = []

        for user_message, bot_response in self.chat_history:
            lines.append(f"Usuário: {user_message}")
            lines.append(f"Assistente: {bot_response}")

        return "\n".join(lines)

    def _emit_complete_response(self, response):
        """Display a complete response gradually in the chat interface."""
        import re
        import time

        response = str(response)
        pieces = re.findall(r"\S+|\s+", response)
        partial_text = ""

        for piece in pieces:
            partial_text += piece
            self.partial.emit(partial_text)
            time.sleep(0.045)

        self.finished.emit(response)

    def run(self):
        import re
        import time

        if self.use_mock:
            model_name = (
                self.llm_config.get("model_name", "mock")
                if self.llm_config
                else "mock"
            )
            response = (
                f"Resposta mockada ({model_name}) para: '{self.prompt}'"
            )
            self._emit_complete_response(response)
            return

        if not self.llm_config:
            error_msg = "Erro: nenhuma configuração de LLM foi recebida."
            self.partial.emit(error_msg)
            self.finished.emit(error_msg)
            return

        try:
            llm = self._create_llm()
            prompt_instruction = self._get_prompt_instruction()
            rag_enabled = bool(self.llm_config.get("rag_enabled"))

            if rag_enabled:
                if not RAG_AVAILABLE:
                    raise RuntimeError(
                        "O backend RAG não pôde ser importado."
                    )

                retriever = self.llm_config.get("retriever")

                if retriever is None:
                    raise ValueError(
                        "O RAG está habilitado, mas nenhum Retriever foi recebido."
                    )

                retrieved_sources = self._retrieve_sources(retriever)
                self.sources.emit(retrieved_sources)

                response = ""
                buffer = ""
                last_emit = 0
                word_pattern = re.compile(r"(\S+\s*)")

                for chunk in stream_chain_with_history(
                    self.chat_history,
                    self.prompt,
                    retriever=retriever,
                    llm=llm,
                    prompt_instruction=prompt_instruction,
                ):
                    buffer += str(chunk)

                    for match in word_pattern.finditer(buffer, last_emit):
                        response = buffer[:match.end()]
                        self.partial.emit(response)
                        last_emit = match.end()
                        time.sleep(0.045)

                if last_emit < len(buffer):
                    self.partial.emit(buffer)
                    response = buffer

                self.finished.emit(response)
                return

            full_prompt = f"""
Siga as orientações abaixo ao responder.

Orientações do usuário:
{prompt_instruction}

Histórico da conversa:
{self._format_history()}

Pergunta atual:
{self.prompt}

Resposta:
"""

            raw_response = llm.invoke(full_prompt)
            self._emit_complete_response(raw_response)

        except Exception as exc:
            error_msg = f"Erro ao processar: {str(exc)}"
            self.partial.emit(error_msg)
            self.finished.emit(error_msg)


# ====================
# Helper Functions
# ====================

def _normalize_csv_row(row):
    normalized = {field: row.get(field, "") for field in CSV_FIELDS}
    if normalized["avaliacao"] in (None, ""):
        normalized["avaliacao"] = "0"
    return normalized


def ensure_csv():
    """Create or migrate conversas.csv without losing old conversations."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
        return

    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames or []
        rows = list(reader)

    if old_fields == CSV_FIELDS:
        return

    temp_file = CSV_FILE + ".tmp"
    with open(temp_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_normalize_csv_row(row))

    os.replace(temp_file, CSV_FILE)


def csv_safe(text: str) -> str:
    if text is None or text == "":
        return "0"
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def csv_unsafe_decode(text: str) -> str:
    if text is None:
        return ""
    return text.replace("\\n", "\n")


def read_all_rows():
    ensure_csv()
    rows = []
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(_normalize_csv_row(row))
    return rows


def _rewrite_csv_rows(rows):
    temp_file = CSV_FILE + ".tmp"
    with open(temp_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_normalize_csv_row(row))
    os.replace(temp_file, CSV_FILE)


def update_rating_only(mensagem_id, new_rating):
    rows = read_all_rows()
    for row in rows:
        if row.get("mensagem_id") == str(mensagem_id):
            row["avaliacao"] = (
                new_rating if new_rating not in (None, "") else "0"
            )
            break
    _rewrite_csv_rows(rows)


def update_chat_title(chat_id, new_title):
    rows = read_all_rows()
    for row in rows:
        if str(row.get("chat_id", "")) == str(chat_id):
            row["chat_title"] = new_title
    _rewrite_csv_rows(rows)


def delete_chat_rows(chat_id):
    rows = [
        row for row in read_all_rows()
        if str(row.get("chat_id", "")) != str(chat_id)
    ]
    _rewrite_csv_rows(rows)


def append_row(row):
    ensure_csv()
    normalized = _normalize_csv_row(row)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(normalized)


def next_message_id():
    rows = read_all_rows()
    max_id = 0
    for r in rows:
        try:
            mid = int(r["mensagem_id"])
            if mid > max_id:
                max_id = mid
        except:
            continue
    return str(max_id + 1)


class ChatMessage:
    def __init__(
        self,
        mensagem_id,
        chat_id,
        mensagem_usuario,
        resposta_bot,
        llm_usada,
        avaliacao="",
        fontes_rag="",
    ):
        self.mensagem_id = str(mensagem_id)
        self.chat_id = str(chat_id)
        self.mensagem_usuario = csv_unsafe_decode(mensagem_usuario)
        self.resposta_bot = csv_unsafe_decode(resposta_bot)
        self.llm_usada = llm_usada
        self.avaliacao = avaliacao
        self.fontes_rag = csv_unsafe_decode(fontes_rag)


class Chat:
    def __init__(self, chat_id, title=None, llm=LLM_DEFAULT):
        self.chat_id = str(chat_id)
        self.title = title or f"Chat {chat_id}"
        self.llm = llm
        self.messages = []


# ====================
# Orange3 Widget
# ====================

class OWChatbot(widget.OWWidget):
    name = "Chatbot"
    description = "Interactive chatbot with RAG capabilities"
    icon = "icons/chatbot.svg"
    priority = 100
    keywords = ["chatbot", "chat", "conversation"]

    # Widget settings
    want_main_area = True
    resizing_enabled = True

    # Settings
    auto_commit = settings.Setting(True)

    class Inputs:
        llm_config = Input("LLM Config", dict)

    class Outputs:
        conversations = Output("Conversations", Table)

    def __init__(self):
        super().__init__()

        ensure_csv()

        # Data
        self.chats = {}
        self.current_chat_id = None
        self.llm_config = None
        self.selected_llm = LLM_DEFAULT

        # GUI
        self._setup_gui()

        # Load existing data
        self.load_chats_from_csv()

        # Update UI
        self.refresh_chat_list()
        if self.chats:
            first_chat_id = sorted(self.chats.keys(), key=lambda x: int(x))[0]
            self.select_chat(first_chat_id)

        # Initially disable controls until LLM is connected
        self.add_chat_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.status_label.setText("Connect an LLM widget to start chatting")
        self._update_chat_management_buttons()

    def _setup_gui(self):
        box = gui.widgetBox(self.controlArea, "Chat Management")

        self.add_chat_button = gui.button(
            box, self, "New Conversation", callback=self.on_add_chat
        )

        self.chat_list_widget = QListWidget()
        self.chat_list_widget.itemClicked.connect(self.on_chat_selected)
        box.layout().addWidget(self.chat_list_widget)

        management_row = QWidget()
        management_layout = QHBoxLayout(management_row)
        management_layout.setContentsMargins(0, 0, 0, 0)
        management_layout.setSpacing(4)

        self.rename_chat_button = QPushButton("Rename")
        self.rename_chat_button.clicked.connect(self.on_rename_chat)
        self.clear_chat_button = QPushButton("Clear")
        self.clear_chat_button.clicked.connect(self.on_clear_chat)
        self.delete_chat_button = QPushButton("Delete")
        self.delete_chat_button.clicked.connect(self.on_delete_chat)

        management_layout.addWidget(self.rename_chat_button)
        management_layout.addWidget(self.clear_chat_button)
        management_layout.addWidget(self.delete_chat_button)
        box.layout().addWidget(management_row)

        llm_box = gui.widgetBox(self.controlArea, "LLM Status")
        self.llm_info_label = gui.label(
            llm_box, self, "Model: not connected"
        )
        self.rag_info_label = gui.label(llm_box, self, "RAG: inactive")
        self.prompt_info_label = gui.label(
            llm_box, self, "Prompt: inactive"
        )
        self.source_info_label = gui.label(
            llm_box, self, "Last sources: —"
        )
        self.source_info_label.setWordWrap(True)

        gui.auto_commit(self.controlArea, self, "auto_commit", "Send")

        self.main_container = QWidget()
        main_layout = QVBoxLayout(self.main_container)

        top_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_content_widget = QWidget()
        self.chat_content_layout = QVBoxLayout(self.chat_content_widget)
        self.chat_content_layout.addStretch(1)
        self.scroll_area.setWidget(self.chat_content_widget)
        main_layout.addWidget(self.scroll_area)

        input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(60)
        self.text_input.keyPressEvent = self.text_input_key_press
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.on_send)
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_button)
        main_layout.addLayout(input_layout)

        self.mainArea.layout().addWidget(self.main_container)

    def _config_status_suffix(self, config):
        """Describe which optional resources are connected to the LLM."""
        if not config:
            return ""

        features = []

        if config.get("rag_enabled"):
            features.append("RAG")

        if config.get("prompt_enabled"):
            features.append("Prompt")

        if not features:
            return ""

        return f" ({' + '.join(features)})"

    @Inputs.llm_config
    def set_llm_config(self, config):
        """Handle input LLM configuration from the LLM widget."""
        self.llm_config = config

        if config is None:
            self.llm_info_label.setText("Model: not connected")
            self.rag_info_label.setText("RAG: inactive")
            self.prompt_info_label.setText("Prompt: inactive")
            self.source_info_label.setText("Last sources: —")
            self.status_label.setText(
                "Connect an LLM widget to start chatting"
            )
            self.send_button.setEnabled(False)
            self.add_chat_button.setEnabled(False)
            self.info.set_input_summary(self.info.NoInput)
            return

        model_name = config.get("model_name", "Unknown")
        mode_status = self._config_status_suffix(config)
        rag_enabled = bool(config.get("rag_enabled"))
        prompt_enabled = bool(config.get("prompt_enabled"))

        self.llm_info_label.setText(f"Model: {model_name}")
        self.rag_info_label.setText(
            "RAG: active" if rag_enabled else "RAG: inactive"
        )
        self.prompt_info_label.setText(
            "Prompt: active" if prompt_enabled else "Prompt: inactive"
        )

        self.add_chat_button.setEnabled(True)

        has_chat = (
            self.current_chat_id is not None
            and self.current_chat_id in self.chats
        )
        self.send_button.setEnabled(has_chat)

        if has_chat:
            self.status_label.setText(
                f"Ready - {model_name}{mode_status}"
            )
            self._update_source_status_from_chat(
                self.chats[self.current_chat_id]
            )
        else:
            self.status_label.setText(
                f"{model_name}{mode_status} connected - "
                "Create a conversation to start"
            )
            self.source_info_label.setText("Last sources: —")

        self.info.set_input_summary(f"{model_name}{mode_status}")
        self.selected_llm = model_name

    def create_star_icon(self, filled=True, color="#FFD700"):
        """Creates a star icon from SVG"""
        if filled:
            svg_data = f'''
            <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path fill="{color}" d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
            </svg>
            '''
        else:
            svg_data = f'''
            <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path fill="none" stroke="{color}" stroke-width="2" d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
            </svg>
            '''
        
        svg_bytes = svg_data.encode('utf-8')
        renderer = QSvgRenderer(svg_bytes)
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)

    def refresh_chat_list(self):
        """Refresh the chat list using readable conversation titles."""
        self.chat_list_widget.clear()

        for cid in sorted(self.chats.keys(), key=lambda x: int(x)):
            chat = self.chats[cid]
            item = QListWidgetItem(chat.title)
            item.setData(Qt.UserRole, cid)
            item.setToolTip(f"Chat {cid} | Model: {chat.llm}")
            self.chat_list_widget.addItem(item)

            if cid == self.current_chat_id:
                self.chat_list_widget.setCurrentItem(item)

        self._update_chat_management_buttons()

    def create_new_chat(self):
        """Create a new chat"""
        if self.chats:
            max_id = max(int(k) for k in self.chats.keys())
            new_id = str(max_id + 1)
        else:
            new_id = "1"
        chat = Chat(new_id, title=f"Chat {new_id}", llm=self.selected_llm)
        self.chats[new_id] = chat
        self.refresh_chat_list()
        return new_id

    def _make_chat_title(self, text, max_length=42):
        title = " ".join((text or "").split()).strip()
        if not title:
            return "New conversation"
        if len(title) <= max_length:
            return title
        return title[: max_length - 1].rstrip() + "…"

    def _update_chat_management_buttons(self):
        has_chat = (
            self.current_chat_id is not None
            and self.current_chat_id in self.chats
        )
        self.rename_chat_button.setEnabled(has_chat)
        self.clear_chat_button.setEnabled(has_chat)
        self.delete_chat_button.setEnabled(has_chat)

    def on_add_chat(self):
        new_id = self.create_new_chat()
        self.select_chat(new_id)

    def on_rename_chat(self):
        if self.current_chat_id not in self.chats:
            return

        chat = self.chats[self.current_chat_id]
        new_title, accepted = QInputDialog.getText(
            self,
            "Rename conversation",
            "Conversation name:",
            text=chat.title,
        )

        if not accepted:
            return

        new_title = " ".join(new_title.split()).strip()
        if not new_title:
            return

        chat.title = new_title
        update_chat_title(chat.chat_id, new_title)
        self.refresh_chat_list()

    def on_clear_chat(self):
        if self.current_chat_id not in self.chats:
            return

        chat = self.chats[self.current_chat_id]
        answer = QMessageBox.question(
            self,
            "Clear conversation",
            f'Clear all messages from "{chat.title}"?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        delete_chat_rows(chat.chat_id)
        chat.messages.clear()
        self.reload_chat_messages()
        self.source_info_label.setText("Last sources: —")
        self.commit.deferred()

    def on_delete_chat(self):
        if self.current_chat_id not in self.chats:
            return

        chat_id = self.current_chat_id
        chat = self.chats[chat_id]

        answer = QMessageBox.question(
            self,
            "Delete conversation",
            f'Delete "{chat.title}" permanently?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        delete_chat_rows(chat_id)
        del self.chats[chat_id]
        self.current_chat_id = None

        self.refresh_chat_list()
        self.reload_chat_messages()
        self.source_info_label.setText("Last sources: —")

        if self.chats:
            next_id = sorted(self.chats.keys(), key=lambda x: int(x))[0]
            self.select_chat(next_id)
        else:
            self.send_button.setEnabled(False)
            self.status_label.setText(
                "Create a conversation to start chatting"
                if self.llm_config is not None
                else "Connect an LLM widget to start chatting"
            )

        self.commit.deferred()

    def on_chat_selected(self, item):
        """Handle chat selection from list"""
        cid = item.data(Qt.UserRole)
        self.select_chat(cid)

    def select_chat(self, chat_id):
        if chat_id not in self.chats:
            return

        self.current_chat_id = chat_id
        chat = self.chats[chat_id]

        for i in range(self.chat_list_widget.count()):
            item = self.chat_list_widget.item(i)
            if item.data(Qt.UserRole) == chat_id:
                self.chat_list_widget.setCurrentItem(item)
                break

        self.reload_chat_messages()
        self._update_chat_management_buttons()
        self._update_source_status_from_chat(chat)

        if self.llm_config is not None:
            self.send_button.setEnabled(True)
            model_name = self.llm_config.get("model_name", "Unknown")
            mode_status = self._config_status_suffix(self.llm_config)
            self.status_label.setText(
                f"Ready - {model_name}{mode_status}"
            )

    def text_input_key_press(self, event):
        """Handle key press events in text input"""
        # Check if Enter is pressed without Shift
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.modifiers() & Qt.ShiftModifier:
                self.on_send()
                event.accept()
                return
        
        QTextEdit.keyPressEvent(self.text_input, event)



    def _format_source_items(self, source_items):
        grouped = {}

        for item in source_items or []:
            label = str(item.get("label", "Documento"))
            chunk = item.get("chunk")
            grouped.setdefault(label, [])

            if chunk is not None and str(chunk) not in grouped[label]:
                grouped[label].append(str(chunk))

        parts = []
        for label, chunks in grouped.items():
            if chunks:
                parts.append(f"{label} (chunks {', '.join(chunks)})")
            else:
                parts.append(label)

        return "; ".join(parts)

    def _handle_worker_sources(self, source_items, user_msg, chat_id):
        formatted = self._format_source_items(source_items)
        user_msg.fontes_rag = formatted

        if self.current_chat_id == chat_id:
            if formatted:
                self.source_info_label.setText(
                    f"Last sources: {formatted}"
                )
            else:
                self.source_info_label.setText(
                    "Last sources: none retrieved"
                )

    def _update_source_status_from_chat(self, chat):
        if not self.llm_config or not self.llm_config.get("rag_enabled"):
            self.source_info_label.setText("Last sources: —")
            return

        for msg in reversed(chat.messages):
            if msg.fontes_rag:
                self.source_info_label.setText(
                    f"Last sources: {msg.fontes_rag}"
                )
                return

        self.source_info_label.setText("Last sources: none yet")

    def clear_layout(self, layout):
        """Clear all widgets from a layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def reload_chat_messages(self):
        """Reload and display all messages in the current chat"""
        self.clear_layout(self.chat_content_layout)
        self.chat_content_layout.addStretch(1)

        if self.current_chat_id is None or self.current_chat_id not in self.chats:
            return

        chat = self.chats[self.current_chat_id]
        for msg in chat.messages:
            self._add_message_widget_to_ui(msg)

        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def _add_message_widget_to_ui(self, msg: ChatMessage):
        """Add a message widget to the UI"""
        # User message (right aligned)
        if msg.mensagem_usuario:
            wrapper = QHBoxLayout()
            bubble = QLabel(msg.mensagem_usuario)
            bubble.setWordWrap(True)
            bubble.setStyleSheet("background-color: #DCF8C6; padding:8px; border-radius:8px;")
            bubble.setMaximumWidth(int(self.width() * 0.6))
            wrapper.addStretch()
            wrapper.addWidget(bubble)
            self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, wrapper)

        # Bot response (left aligned) with star rating
        if msg.resposta_bot:
            bot_layout = QVBoxLayout()
            
            bubble = QLabel(msg.resposta_bot)
            bubble.setWordWrap(True)
            bubble.setStyleSheet("background-color: #FFFFFF; padding:8px; border-radius:8px;")
            bubble.setMaximumWidth(int(self.width() * 0.6))
            
            msg_row = QHBoxLayout()
            msg_row.addWidget(bubble)
            msg_row.addStretch()
            
            bot_layout.addLayout(msg_row)

            if msg.fontes_rag:
                source_label = QLabel(
                    f"Sources retrieved: {msg.fontes_rag}"
                )
                source_label.setWordWrap(True)
                source_label.setMaximumWidth(int(self.width() * 0.6))
                source_label.setStyleSheet(
                    "color: #666666; font-size: 10px; "
                    "padding: 2px 8px 4px 8px;"
                )
                bot_layout.addWidget(source_label)

            # Star rating
            stars_layout = QHBoxLayout()
            stars_layout.setSpacing(0)
            stars_layout.setContentsMargins(0, 0, 0, 0)
            
            current_rating = 0
            if msg.avaliacao:
                try:
                    current_rating = int(msg.avaliacao)
                except:
                    pass
            
            star_buttons = []
            for i in range(1, 6):
                star_btn = QPushButton()
                star_btn.setFixedSize(30, 30)
                star_btn.setCursor(Qt.PointingHandCursor)
                star_btn.setProperty("star_index", i)
                star_btn.setProperty("message_id", msg.mensagem_id)
                star_btn.setProperty("current_rating", current_rating)
                
                if i <= current_rating:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#FFD700"))
                else:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#D3D3D3"))
                
                star_btn.setIconSize(QSize(24, 24))
                star_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        padding: 0px;
                    }
                """)
                
                star_btn.enterEvent = lambda event, btn=star_btn, idx=i, buttons=star_buttons: self.on_star_hover(btn, idx, buttons)
                star_btn.leaveEvent = lambda event, buttons=star_buttons: self.on_star_leave(buttons)
                star_btn.clicked.connect(lambda checked, mid=msg.mensagem_id, rating=i: self.on_star_clicked(mid, rating))
                
                star_buttons.append(star_btn)
                stars_layout.addWidget(star_btn)
            
            stars_layout.addStretch()
            bot_layout.addLayout(stars_layout)
            
            self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, bot_layout)

    def on_star_hover(self, button, hover_index, star_buttons):
        """Highlight stars on hover"""
        for i, star_btn in enumerate(star_buttons, 1):
            if i <= hover_index:
                star_btn.setIcon(self.create_star_icon(filled=True, color="#FFD700"))
            else:
                star_btn.setIcon(self.create_star_icon(filled=True, color="#D3D3D3"))
    
    def on_star_leave(self, star_buttons):
        """Restore star state when mouse leaves"""
        if star_buttons:
            current_rating = star_buttons[0].property("current_rating")
            for i, star_btn in enumerate(star_buttons, 1):
                if i <= current_rating:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#FFD700"))
                else:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#D3D3D3"))

    def on_send(self):
        """Handle send message"""
        text = self.text_input.toPlainText().strip()

        if not text or self.current_chat_id is None:
            return

        if self.llm_config is None:
            self.status_label.setText(
                "Connect an LLM widget before sending a message"
            )
            return

        chat = self.chats[self.current_chat_id]
        llm_used = self.llm_config.get(
            "model_name",
            chat.llm,
        )
        chat.llm = llm_used

        if not chat.messages and chat.title.startswith("Chat "):
            chat.title = self._make_chat_title(text)
            self.refresh_chat_list()

        mid = next_message_id()

        # Add user message
        user_msg = ChatMessage(
            mensagem_id=mid,
            chat_id=self.current_chat_id,
            mensagem_usuario=text,
            resposta_bot="",
            llm_usada=llm_used
        )
        chat.messages.append(user_msg)
        self._add_message_widget_to_ui(user_msg)
        self.text_input.clear()

        # Add typing indicator
        typing_label, typing_layout = self.add_typing_indicator()

        # Prepare history
        chat_history = [
            (m.mensagem_usuario, m.resposta_bot)
            for m in chat.messages[:-1]
            if m.mensagem_usuario and m.resposta_bot
        ]

        self.set_sending_state(True)

        # Add placeholder for bot reply
        bot_bubble = QLabel("")
        bot_bubble.setWordWrap(True)
        bot_bubble.setStyleSheet("background-color: #FFFFFF; padding:8px; border-radius:8px;")
        bot_bubble.setMaximumWidth(int(self.width() * 0.6))
        bot_row = QHBoxLayout()
        bot_row.addWidget(bot_bubble)
        bot_row.addStretch()
        self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, bot_row)
        bot_bubble.setVisible(False)

        # Check if we should use mock mode
        use_mock = os.getenv('CHATBOT_UI_ONLY', 'false').lower() in ('true', '1', 'yes')
        
        # Start worker thread
        self.worker = LLMWorker(
            llm_config=self.llm_config,
            chat_history=chat_history,
            prompt=text,
            use_mock=use_mock
        )

        self._streaming_started = False
        def update_bot_bubble(partial_text):
            if not self._streaming_started:
                typing_label.deleteLater()
                self.chat_content_layout.removeItem(typing_layout)
                bot_bubble.setVisible(True)
                self._streaming_started = True
            bot_bubble.setText(partial_text)
            user_msg.resposta_bot = partial_text
            self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            )

        # Capture the chat_id to prevent context bleeding if user switches chats
        originating_chat_id = self.current_chat_id
        
        self.worker.partial.connect(update_bot_bubble)
        self.worker.sources.connect(
            lambda source_items: self._handle_worker_sources(
                source_items,
                user_msg,
                originating_chat_id,
            )
        )
        self.worker.finished.connect(
            lambda response: self.on_llm_finished(response, user_msg, bot_bubble, bot_row, originating_chat_id)
        )
        self.worker.start()

    def on_star_clicked(self, mensagem_id, rating):
        """Handle star rating click"""
        mid = str(mensagem_id)
        found = None
        for chat in self.chats.values():
            for m in chat.messages:
                if m.mensagem_id == mid:
                    found = m
                    break
            if found:
                break
        if not found:
            return
        
        # Toggle rating
        if found.avaliacao == str(rating):
            found.avaliacao = ""
        else:
            found.avaliacao = str(rating)

        # Update CSV
        rows = read_all_rows()
        changed = False
        for r in rows:
            if str(r.get("mensagem_id", "")) == mid:
                r["avaliacao"] = found.avaliacao
                changed = True
                break
        if changed:
            update_rating_only(mensagem_id, found.avaliacao)
        else:
            chat = self.chats.get(found.chat_id)
            row = {
                "mensagem_id": found.mensagem_id,
                "chat_id": found.chat_id,
                "chat_title": chat.title if chat else "",
                "mensagem_usuario": csv_safe(found.mensagem_usuario),
                "resposta_bot": csv_safe(found.resposta_bot),
                "llm_usada": found.llm_usada,
                "avaliacao": found.avaliacao,
                "fontes_rag": csv_safe(found.fontes_rag)
                if found.fontes_rag else "",
            }
            append_row(row)
        
        self.reload_chat_messages()
        self.commit.deferred()

    def load_chats_from_csv(self):
        rows = read_all_rows()

        for row in rows:
            cid = row.get("chat_id", "1") or "1"
            stored_title = csv_unsafe_decode(
                row.get("chat_title", "")
            ).strip()

            if stored_title == "0":
                stored_title = ""

            if cid not in self.chats:
                self.chats[cid] = Chat(
                    cid,
                    title=stored_title or f"Chat {cid}",
                    llm=row.get("llm_usada", LLM_DEFAULT)
                    or LLM_DEFAULT,
                )
            else:
                if stored_title:
                    self.chats[cid].title = stored_title

            msg = ChatMessage(
                mensagem_id=row.get("mensagem_id", ""),
                chat_id=cid,
                mensagem_usuario=csv_unsafe_decode(
                    row.get("mensagem_usuario", "")
                ),
                resposta_bot=csv_unsafe_decode(
                    row.get("resposta_bot", "")
                ),
                llm_usada=row.get("llm_usada", LLM_DEFAULT)
                or LLM_DEFAULT,
                avaliacao=row.get("avaliacao", "") or "",
                fontes_rag=csv_unsafe_decode(
                    row.get("fontes_rag", "")
                ),
            )
            self.chats[cid].messages.append(msg)

        for chat in self.chats.values():
            if chat.title.startswith("Chat ") and chat.messages:
                chat.title = self._make_chat_title(
                    chat.messages[0].mensagem_usuario
                )

    def add_typing_indicator(self):
        """Add typing indicator to chat"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        spinner = SpinnerLabel()
        typing = TypingLabel()

        layout.addWidget(spinner)
        layout.addWidget(typing)
        layout.addStretch()

        container.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-radius: 8px;
            }
        """)
        container.setMaximumWidth(int(self.width() * 0.4))

        row = QHBoxLayout()
        row.addWidget(container)
        row.addStretch()

        self.chat_content_layout.insertLayout(
            self.chat_content_layout.count() - 1, row
        )

        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

        return container, row

    def on_llm_finished(self, response, user_msg, bot_bubble, bot_row, originating_chat_id):
        """Handle LLM response completion"""
        bot_bubble.setVisible(True)
        bot_bubble.setText(response)
        user_msg.resposta_bot = response

        chat = self.chats.get(user_msg.chat_id)

        append_row({
            "mensagem_id": user_msg.mensagem_id,
            "chat_id": user_msg.chat_id,
            "chat_title": chat.title if chat else "",
            "mensagem_usuario": csv_safe(user_msg.mensagem_usuario),
            "resposta_bot": csv_safe(user_msg.resposta_bot),
            "llm_usada": user_msg.llm_usada,
            "avaliacao": user_msg.avaliacao,
            "fontes_rag": csv_safe(user_msg.fontes_rag)
            if user_msg.fontes_rag else "",
        })

        self.set_sending_state(False)
        
        # Only reload if we're still viewing the same chat where the message was sent
        # This prevents context bleeding if user switched chats during LLM processing
        if self.current_chat_id == originating_chat_id:
            self.reload_chat_messages()
        
        self.commit.deferred()

    def set_sending_state(self, sending: bool):
        self.send_button.setDisabled(sending)
        self.text_input.setDisabled(sending)

        has_chat = (
            self.current_chat_id is not None
            and self.current_chat_id in self.chats
        )
        self.rename_chat_button.setDisabled(sending or not has_chat)
        self.clear_chat_button.setDisabled(sending or not has_chat)
        self.delete_chat_button.setDisabled(sending or not has_chat)

    @gui.deferred
    def commit(self):
        """Send output data to Orange workflow"""
        if not self.chats:
            self.Outputs.conversations.send(None)
            return

        # Convert conversations to Orange Table
        data_rows = []
        for chat in self.chats.values():
            for msg in chat.messages:
                if msg.mensagem_usuario and msg.resposta_bot:
                    data_rows.append([
                        msg.chat_id,
                        msg.mensagem_usuario,
                        msg.resposta_bot,
                        msg.llm_usada,
                        msg.avaliacao or "0"
                    ])

        if not data_rows:
            self.Outputs.conversations.send(None)
            return

        # Create Orange Table
        domain = Domain(
            [],
            metas=[
                StringVariable("chat_id"),
                StringVariable("user_message"),
                StringVariable("bot_response"),
                StringVariable("llm_used"),
                StringVariable("rating")
            ]
        )

        table = Table.from_list(domain, [[]] * len(data_rows))
        for i, row in enumerate(data_rows):
            table.metas[i] = row

        self.Outputs.conversations.send(table)
        self.info.set_output_summary(f"{len(data_rows)} messages")


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWChatbot).run()
