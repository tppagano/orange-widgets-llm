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
    QListWidgetItem, QLabel, QScrollArea, QTextEdit, QWidget
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
LLM_DEFAULT = "gemma3"


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

    def __init__(self, llm_config, chat_history, prompt, use_mock=False):
        super().__init__()
        self.llm_config = llm_config
        self.chat_history = chat_history
        self.prompt = prompt
        self.use_mock = use_mock

    def run(self):
        import time
        import re
        
        if self.use_mock:
            model_name = self.llm_config.get("model_name", "mock") if self.llm_config else "mock"
            response = f"Resposta mockada ({model_name}) para: '{self.prompt}'"
            words = re.findall(r'\S+|\s+', response)
            out = ""
            for word in words:
                out += word
                self.partial.emit(out)
                time.sleep(0.045)
            self.finished.emit(response)
        elif not RAG_AVAILABLE or not self.llm_config or not self.llm_config.get("rag_enabled"):
            # Simple response without RAG
            model_name = self.llm_config.get("model_name", "unknown") if self.llm_config else "unknown"
            response = f"[Modo simples - sem RAG] Modelo: {model_name}. Você perguntou: '{self.prompt}'"
            words = re.findall(r'\S+|\s+', response)
            out = ""
            for word in words:
                out += word
                self.partial.emit(out)
                time.sleep(0.045)
            self.finished.emit(response)
        else:
            # Use RAG with retriever from llm_config
            try:
                retriever = self.llm_config.get("retriever")
                model_config = self.llm_config
                
                # Create LLM instance based on model_type
                if model_config["model_type"] == "ollama":
                    from langchain_community.llms import Ollama
                    llm = Ollama(
                        model=model_config["model"],
                        temperature=model_config.get("temperature", 0.7),
                        num_ctx=model_config.get("max_tokens", 4096)
                    )
                else:
                    raise ValueError(f"Unknown model type: {model_config['model_type']}")
                
                response = ""
                buffer = ""
                last_emit = 0
                word_pattern = re.compile(r'(\S+\s*)')
                for chunk in stream_chain_with_history(self.chat_history, self.prompt, retriever=retriever, llm=llm):
                    buffer += chunk
                    for match in word_pattern.finditer(buffer, last_emit):
                        response = buffer[:match.end()]
                        self.partial.emit(response)
                        last_emit = match.end()
                        time.sleep(0.045)
                if last_emit < len(buffer):
                    self.partial.emit(buffer)
                    response = buffer
                self.finished.emit(response)
            except Exception as e:
                error_msg = f"Erro ao processar: {str(e)}"
                self.partial.emit(error_msg)
                self.finished.emit(error_msg)


# ====================
# Helper Functions
# ====================

def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["mensagem_id", "chat_id", "mensagem_usuario", "resposta_bot", "llm_usada", "avaliacao"])


def csv_safe(text: str) -> str:
    if text is None or text == "":
        return "0"
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def csv_unsafe_decode(text: str) -> str:
    if text is None:
        return ""
    return text.replace("\\n", "\n")


def read_all_rows():
    rows = []
    if not os.path.exists(CSV_FILE):
        return rows
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def update_rating_only(mensagem_id, new_rating):
    temp_file = CSV_FILE + ".tmp"

    with open(CSV_FILE, "r", newline="", encoding="utf-8") as src, \
         open(temp_file, "w", newline="", encoding="utf-8") as dst:

        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames

        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            if row.get("mensagem_id") == str(mensagem_id):
                row["avaliacao"] = new_rating if new_rating not in (None, "") else "0"
            if row["avaliacao"] in (None, ""):
                row["avaliacao"] = "0"
            writer.writerow(row)

    os.replace(temp_file, CSV_FILE)


def append_row(row):
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["mensagem_id", "chat_id", "mensagem_usuario", "resposta_bot", "llm_usada", "avaliacao"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        if "avaliacao" in row and (row["avaliacao"] is None or row["avaliacao"] == ""):
            row["avaliacao"] = "0"
        writer.writerow(row)


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
    def __init__(self, mensagem_id, chat_id, mensagem_usuario, resposta_bot, llm_usada, avaliacao=""):
        self.mensagem_id = str(mensagem_id)
        self.chat_id = str(chat_id)
        self.mensagem_usuario = csv_unsafe_decode(mensagem_usuario)
        self.resposta_bot = csv_unsafe_decode(resposta_bot)
        self.llm_usada = llm_usada
        self.avaliacao = avaliacao


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

        # GUI
        self._setup_gui()

        # Load existing data
        self.load_chats_from_csv()

        # Create initial chat if needed
        if not self.chats:
            self.create_new_chat()

        # Update UI
        self.refresh_chat_list()
        if self.chats:
            first_chat_id = sorted(self.chats.keys(), key=lambda x: int(x))[0]
            self.select_chat(first_chat_id)

        # Note: Document vectorization is now done manually via "Add Documents" button
        # to avoid blocking the UI during widget initialization

    def _setup_gui(self):
        # Control area (left panel)
        box = gui.widgetBox(self.controlArea, "Chat Management")
        
        self.add_chat_button = gui.button(
            box, self, "New Conversation", callback=self.on_add_chat
        )

        self.chat_list_widget = QListWidget()
        self.chat_list_widget.itemClicked.connect(self.on_chat_selected)
        box.layout().addWidget(self.chat_list_widget)

        # LLM Config info
        llm_box = gui.widgetBox(self.controlArea, "LLM Status")
        self.llm_info_label = gui.label(llm_box, self, "No LLM connected")

        # Auto-commit
        gui.auto_commit(self.controlArea, self, "auto_commit", "Send")

        # Main area (right panel - chat interface)
        self.main_container = QWidget()
        main_layout = QVBoxLayout(self.main_container)

        # Status bar at top
        top_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # Chat scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_content_widget = QWidget()
        self.chat_content_layout = QVBoxLayout(self.chat_content_widget)
        self.chat_content_layout.addStretch(1)
        self.scroll_area.setWidget(self.chat_content_widget)
        main_layout.addWidget(self.scroll_area)

        # Input area
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

    @Inputs.llm_config
    def set_llm_config(self, config):
        """Handle input LLM configuration from LLM widget"""
        self.llm_config = config
        
        if config is None:
            self.llm_info_label.setText("No LLM connected")
            self.status_label.setText("Connect an LLM widget to start chatting")
            self.send_button.setEnabled(False)
            self.info.set_input_summary(self.info.NoInput)
        else:
            model_name = config.get("model_name", "Unknown")
            rag_status = " (RAG)" if config.get("rag_enabled") else ""
            self.llm_info_label.setText(f"✓ {model_name}{rag_status}")
            self.status_label.setText(f"Ready - {model_name}{rag_status}")
            self.send_button.setEnabled(True)
            self.info.set_input_summary(f"{model_name}{rag_status}")

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
        """Refresh the chat list widget"""
        self.chat_list_widget.clear()
        for cid in sorted(self.chats.keys(), key=lambda x: int(x)):
            chat = self.chats[cid]
            item = QListWidgetItem(f"{chat.title} ({chat.llm})")
            item.setData(Qt.UserRole, cid)
            self.chat_list_widget.addItem(item)

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

    def on_add_chat(self):
        """Handle add chat button"""
        new_id = self.create_new_chat()
        self.select_chat(new_id)

    def on_chat_selected(self, item):
        """Handle chat selection from list"""
        cid = item.data(Qt.UserRole)
        self.select_chat(cid)

    def select_chat(self, chat_id):
        """Select a specific chat"""
        if chat_id not in self.chats:
            return
        self.current_chat_id = chat_id
        chat = self.chats[chat_id]

        # Mark item in list
        for i in range(self.chat_list_widget.count()):
            it = self.chat_list_widget.item(i)
            if it.data(Qt.UserRole) == chat_id:
                self.chat_list_widget.setCurrentItem(it)
                break

        # Load messages
        self.reload_chat_messages()

    def text_input_key_press(self, event):
        """Handle key press events in text input"""
        # Check if Enter is pressed without Shift
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.modifiers() & Qt.ShiftModifier:
                self.on_send()
                event.accept()
                return
        
        QTextEdit.keyPressEvent(self.text_input, event)



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

        chat = self.chats[self.current_chat_id]
        llm_used = chat.llm
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

        self.worker.partial.connect(update_bot_bubble)
        self.worker.finished.connect(
            lambda response: self.on_llm_finished(response, user_msg, bot_bubble, bot_row)
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
            row = {
                "mensagem_id": found.mensagem_id,
                "chat_id": found.chat_id,
                "mensagem_usuario": csv_safe(found.mensagem_usuario),
                "resposta_bot": csv_safe(found.resposta_bot),
                "llm_usada": found.llm_usada,
                "avaliacao": found.avaliacao
            }
            append_row(row)
        
        self.reload_chat_messages()
        self.commit.deferred()

    def load_chats_from_csv(self):
        """Load existing chats from CSV"""
        rows = read_all_rows()
        for r in rows:
            cid = r.get("chat_id", "1") or "1"
            if cid not in self.chats:
                chat = Chat(cid, title=f"Chat {cid}", llm=r.get("llm_usada", LLM_DEFAULT) or LLM_DEFAULT)
                self.chats[cid] = chat
            else:
                if not self.chats[cid].llm:
                    self.chats[cid].llm = r.get("llm_usada", LLM_DEFAULT) or LLM_DEFAULT

            msg = ChatMessage(
                mensagem_id=r.get("mensagem_id", ""),
                chat_id=cid,
                mensagem_usuario=csv_unsafe_decode(r.get("mensagem_usuario", "")),
                resposta_bot=csv_unsafe_decode(r.get("resposta_bot", "")),
                llm_usada=r.get("llm_usada", LLM_DEFAULT) or LLM_DEFAULT,
                avaliacao=r.get("avaliacao", "") or ""
            )
            self.chats[cid].messages.append(msg)

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

    def on_llm_finished(self, response, user_msg, bot_bubble, bot_row):
        """Handle LLM response completion"""
        bot_bubble.setVisible(True)
        bot_bubble.setText(response)
        user_msg.resposta_bot = response

        append_row({
            "mensagem_id": user_msg.mensagem_id,
            "chat_id": user_msg.chat_id,
            "mensagem_usuario": csv_safe(user_msg.mensagem_usuario),
            "resposta_bot": csv_safe(user_msg.resposta_bot),
            "llm_usada": user_msg.llm_usada,
            "avaliacao": user_msg.avaliacao
        })

        self.set_sending_state(False)
        self.reload_chat_messages()
        self.commit.deferred()

    def set_sending_state(self, sending: bool):
        """Enable/disable UI during message sending"""
        self.send_button.setDisabled(sending)
        self.text_input.setDisabled(sending)

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
