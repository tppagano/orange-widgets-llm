# chatbot_gui_fix.py
import sys
import os
import csv

# UI_ONLY MODE: When enabled, uses mock responses without loading the LLM
UI_ONLY_MODE = os.getenv('CHATBOT_UI_ONLY', 'false').lower() in ('true', '1', 'yes')

if not UI_ONLY_MODE:
    from rag_backend import create_chain_with_history, ingest_pdfs


from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QScrollArea, QTextEdit, QComboBox,
    QMessageBox, QFileDialog, QProgressDialog, QDialog
)
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer




CSV_FILE = "conversas.csv"
LLM_DEFAULT = "gemma3"
LLM_OPTIONS = ["gemma3", "gpt-4o-mini", "gpt-4o", "llama2", "local-llm"]

import glob

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



# --- Streaming LLMWorker ---
class LLMWorker(QThread):
    partial = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, llm_used, chat_history, prompt, ui_only=False):
        super().__init__()
        self.llm_used = llm_used
        self.chat_history = chat_history
        self.prompt = prompt
        self.ui_only = ui_only

    def run(self):
        import time
        import re
        if self.ui_only:
            response = f"Resposta mockada ({self.llm_used}) para: '{self.prompt}'"
            words = re.findall(r'\S+|\s+', response)
            out = ""
            for word in words:
                out += word
                self.partial.emit(out)
                time.sleep(0.045)
            self.finished.emit(response)
        else:
            from rag_backend import stream_chain_with_history
            response = ""
            buffer = ""
            last_emit = 0
            word_pattern = re.compile(r'(\S+\s*)')
            for chunk in stream_chain_with_history(self.chat_history, self.prompt):
                buffer += chunk
                # Find all new words since last_emit
                for match in word_pattern.finditer(buffer, last_emit):
                    response = buffer[:match.end()]
                    self.partial.emit(response)
                    last_emit = match.end()
                    time.sleep(0.045)
            # Emit any remaining text
            if last_emit < len(buffer):
                self.partial.emit(buffer)
                response = buffer
            self.finished.emit(response)

class DocumentIngestWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, files):
        super().__init__()
        self.files = files

    def run(self):
        try:
            ingest_pdfs(self.files)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


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
            # Always save as '0' if empty
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
        # Always save as '0' if empty
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


class ChatBotUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chatbot - PyQt5")
        self.setMinimumSize(900, 600)

        ensure_csv()

        # Scan 'input' folder for new PDFs to vectorize
        self.vectorize_new_documents()

        # memória
        self.chats = {}
        self.current_chat_id = None

        # UI primeiro (para evitar AttributeError)
        self.setup_ui()

        # carrega dados existentes (agora que UI existe)
        self.load_chats_from_csv()

        # Se não houver chats, cria um inicial
        if not self.chats:
            self.create_new_chat()

        # atualiza listagem e seleciona primeiro chat
        self.refresh_chat_list()
        if self.chats:
            first_chat_id = sorted(self.chats.keys(), key=lambda x: int(x))[0]
            self.select_chat(first_chat_id)

    def vectorize_new_documents(self):
        
        input_dir = os.path.join(os.getcwd(), "input")
        if not os.path.exists(input_dir):
            os.makedirs(input_dir)
        
        pdf_files = glob.glob(os.path.join(input_dir, "*.pdf"))
        if pdf_files:
            try:
                from rag_backend import ingest_pdfs
                ingest_pdfs(pdf_files)
            except Exception as e:
                print(f"Erro ao vetorizando documentos: {e}")
            # UI primeiro (para evitar AttributeError)
            self.setup_ui()
            # Add document selector button to the left panel
            doc_btn = QPushButton("Selecionar documentos")
            doc_btn.clicked.connect(self.show_document_selector)
            self.layout().itemAt(0).widget().layout().insertWidget(1, doc_btn)

    def show_document_selector(self):
        input_dir = os.path.join(os.getcwd(), "input")
        pdf_files = glob.glob(os.path.join(input_dir, "*.pdf"))
        dialog = QDialog(self)
        dialog.setWindowTitle("Selecionar documentos para o chatbot")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        label = QLabel("Selecione os documentos que o chatbot pode acessar:")
        layout.addWidget(label)
        list_widget = QListWidget()
        for pdf in pdf_files:
            item = QListWidgetItem(os.path.basename(pdf))
            item.setData(Qt.UserRole, pdf)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Pre-check if currently enabled
            if pdf in getattr(self, "enabled_documents", pdf_files):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancelar")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        def accept():
            self.enabled_documents = [item.data(Qt.UserRole) for i in range(list_widget.count())
                                      if list_widget.item(i).checkState() == Qt.Checked]
            dialog.accept()
        def reject():
            dialog.reject()
        ok_btn.clicked.connect(accept)
        cancel_btn.clicked.connect(reject)
        dialog.exec_()

    def get_enabled_documents(self):
        input_dir = os.path.join(os.getcwd(), "input")
        pdf_files = glob.glob(os.path.join(input_dir, "*.pdf"))
        return getattr(self, "enabled_documents", pdf_files)

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

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()

        # Left
        self.add_chat_button = QPushButton("Adicionar conversa")
        self.add_chat_button.clicked.connect(self.on_add_chat)
        left_panel.addWidget(self.add_chat_button)

        self.chat_list_widget = QListWidget()
        self.chat_list_widget.itemClicked.connect(self.on_chat_selected)
        left_panel.addWidget(self.chat_list_widget)

        left_container = QWidget()
        left_container.setLayout(left_panel)
        left_container.setMaximumWidth(300)

        # Right - topo com selector de LLM
        top_right = QHBoxLayout()
        top_right.addWidget(QLabel("LLM do chat:"))
        self.llm_selector = QComboBox()
        self.llm_selector.addItems(LLM_OPTIONS)
        self.llm_selector.currentIndexChanged.connect(self.on_llm_changed)
        top_right.addWidget(self.llm_selector)
        top_right.addStretch()
        right_panel.addLayout(top_right)

        # scroll area das mensagens
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_content_widget = QWidget()
        self.chat_content_layout = QVBoxLayout(self.chat_content_widget)
        self.chat_content_layout.addStretch(1)
        self.scroll_area.setWidget(self.chat_content_widget)
        right_panel.addWidget(self.scroll_area)

        # input
        input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(60)
        self.text_input.keyPressEvent = self.text_input_key_press
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self.on_send)
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_button)
        right_panel.addLayout(input_layout)

        right_container = QWidget()
        right_container.setLayout(right_panel)

        main_layout.addWidget(left_container)
        main_layout.addWidget(right_container)
        self.setLayout(main_layout)

    def refresh_chat_list(self):
        self.chat_list_widget.clear()
        for cid in sorted(self.chats.keys(), key=lambda x: int(x)):
            chat = self.chats[cid]
            item = QListWidgetItem(f"{chat.title} ({chat.llm})")
            item.setData(Qt.UserRole, cid)
            self.chat_list_widget.addItem(item)

    def create_new_chat(self):
        if self.chats:
            max_id = max(int(k) for k in self.chats.keys())
            new_id = str(max_id + 1)
        else:
            new_id = "1"
        chat = Chat(new_id, title=f"Chat {new_id}", llm=LLM_DEFAULT)
        self.chats[new_id] = chat
        self.refresh_chat_list()
        return new_id

    def on_add_chat(self):
        new_id = self.create_new_chat()
        self.select_chat(new_id)

    def on_chat_selected(self, item):
        cid = item.data(Qt.UserRole)
        self.select_chat(cid)

    def select_chat(self, chat_id):
        if chat_id not in self.chats:
            return
        self.current_chat_id = chat_id
        chat = self.chats[chat_id]

        # atualiza combobox de LLM - bloqueia sinais para não disparar on_llm_changed
        try:
            idx = LLM_OPTIONS.index(chat.llm)
        except ValueError:
            idx = 0
        self.llm_selector.blockSignals(True)
        self.llm_selector.setCurrentIndex(idx)
        self.llm_selector.blockSignals(False)

        # marca item na lista
        for i in range(self.chat_list_widget.count()):
            it = self.chat_list_widget.item(i)
            if it.data(Qt.UserRole) == chat_id:
                self.chat_list_widget.setCurrentItem(it)
                break

        # carrega mensagens
        self.reload_chat_messages()

    def text_input_key_press(self, event):
        """Handle key press events in text input"""
        from PyQt5.QtCore import Qt as QtKey
        
        # Check if Enter is pressed without Shift
        if event.key() in (QtKey.Key_Return, QtKey.Key_Enter):
            if not event.modifiers() & QtKey.ShiftModifier:
                # Send message
                self.on_send()
                event.accept()
                return
            # If Shift+Enter, allow new line (default behavior)
        
        # Call the original keyPressEvent for other keys
        QTextEdit.keyPressEvent(self.text_input, event)

    def on_llm_changed(self, index):
        if self.current_chat_id is None:
            return
        new_llm = LLM_OPTIONS[index]
        self.chats[self.current_chat_id].llm = new_llm
        self.refresh_chat_list()
        self.select_chat(self.current_chat_id)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
        return

    def reload_chat_messages(self):
        # limpa tudo e adiciona stretch final
        self.clear_layout(self.chat_content_layout)
        self.chat_content_layout.addStretch(1)

        chat = self.chats[self.current_chat_id]
        for msg in chat.messages:
            self._add_message_widget_to_ui(msg)

        # scroll ao final
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def _add_message_widget_to_ui(self, msg: ChatMessage):
        # Mensagem do usuário (direita)
        if msg.mensagem_usuario:
            wrapper = QHBoxLayout()
            bubble = QLabel(msg.mensagem_usuario)
            bubble.setWordWrap(True)
            bubble.setStyleSheet("background-color: #DCF8C6; padding:8px; border-radius:8px;")
            bubble.setMaximumWidth(int(self.width() * 0.6))
            wrapper.addStretch()
            wrapper.addWidget(bubble)
            self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, wrapper)

        # Resposta do bot (esquerda) + estrelas para avaliação
        if msg.resposta_bot:
            bot_layout = QVBoxLayout()
            
            # Bubble da resposta
            bubble = QLabel(msg.resposta_bot)
            bubble.setWordWrap(True)
            bubble.setStyleSheet("background-color: #FFFFFF; padding:8px; border-radius:8px;")
            bubble.setMaximumWidth(int(self.width() * 0.6))
            
            # Container horizontal para a bubble e estrelas
            msg_row = QHBoxLayout()
            msg_row.addWidget(bubble)
            msg_row.addStretch()
            
            bot_layout.addLayout(msg_row)
            
            # Linha de estrelas
            stars_layout = QHBoxLayout()
            stars_layout.setSpacing(0)  # Remove spacing between star buttons
            stars_layout.setContentsMargins(0, 0, 0, 0)
            
            current_rating = 0
            if msg.avaliacao:
                try:
                    current_rating = int(msg.avaliacao)
                except:
                    pass
            
            # Criar 5 botões de estrela
            star_buttons = []
            for i in range(1, 6):
                star_btn = QPushButton()
                star_btn.setFixedSize(30, 30)
                star_btn.setCursor(Qt.PointingHandCursor)
                star_btn.setProperty("star_index", i)
                star_btn.setProperty("message_id", msg.mensagem_id)
                star_btn.setProperty("current_rating", current_rating)
                
                # Define o ícone baseado na avaliação atual
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
                
                # Eventos de mouse para hover effect
                star_btn.enterEvent = lambda event, btn=star_btn, idx=i, buttons=star_buttons: self.on_star_hover(btn, idx, buttons)
                star_btn.leaveEvent = lambda event, buttons=star_buttons: self.on_star_leave(buttons)
                
                # Conecta o clique
                star_btn.clicked.connect(lambda checked, mid=msg.mensagem_id, rating=i: self.on_star_clicked(mid, rating))
                
                star_buttons.append(star_btn)
                stars_layout.addWidget(star_btn)
            
            stars_layout.addStretch()
            bot_layout.addLayout(stars_layout)
            
            self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, bot_layout)

    def on_star_hover(self, button, hover_index, star_buttons):
        """Ilumina as estrelas até a posição do hover"""
        for i, star_btn in enumerate(star_buttons, 1):
            if i <= hover_index:
                star_btn.setIcon(self.create_star_icon(filled=True, color="#FFD700"))
            else:
                star_btn.setIcon(self.create_star_icon(filled=True, color="#D3D3D3"))
    
    def on_star_leave(self, star_buttons):
        """Volta ao estado baseado na avaliação atual quando o mouse sai"""
        if star_buttons:
            current_rating = star_buttons[0].property("current_rating")
            for i, star_btn in enumerate(star_buttons, 1):
                if i <= current_rating:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#FFD700"))
                else:
                    star_btn.setIcon(self.create_star_icon(filled=True, color="#D3D3D3"))

    def on_send(self):
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

        # Add typing indicator and prepare for streaming
        typing_label, typing_layout = self.add_typing_indicator()

        # Prepare history
        chat_history = [
            (m.mensagem_usuario, m.resposta_bot)
            for m in chat.messages[:-1]
            if m.mensagem_usuario and m.resposta_bot
        ]

        self.set_sending_state(True)

        # Add a placeholder for the bot reply bubble (hidden initially)
        bot_bubble = QLabel("")
        bot_bubble.setWordWrap(True)
        bot_bubble.setStyleSheet("background-color: #FFFFFF; padding:8px; border-radius:8px;")
        bot_bubble.setMaximumWidth(int(self.width() * 0.6))
        bot_row = QHBoxLayout()
        bot_row.addWidget(bot_bubble)
        bot_row.addStretch()
        # Insert after typing indicator, but before the stretch
        self.chat_content_layout.insertLayout(self.chat_content_layout.count() - 1, bot_row)
        bot_bubble.setVisible(False)

        # Start worker thread with streaming
        self.worker = LLMWorker(
            llm_used=llm_used,
            chat_history=chat_history,
            prompt=text,
            ui_only=UI_ONLY_MODE
        )

        # For streaming: update the bot reply bubble as tokens arrive
        self._streaming_started = False
        def update_bot_bubble(partial_text):
            if not self._streaming_started:
                # Remove typing indicator and show the bubble
                typing_label.deleteLater()
                self.chat_content_layout.removeItem(typing_layout)
                bot_bubble.setVisible(True)
                self._streaming_started = True
            bot_bubble.setText(partial_text)
            user_msg.resposta_bot = partial_text
            # Scroll to bottom as text grows
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

        self.worker.partial.connect(update_bot_bubble)
        self.worker.finished.connect(
            lambda response: self.on_llm_finished(
                response, user_msg, bot_bubble, bot_row
            )
        )
        self.worker.start()


    def on_star_clicked(self, mensagem_id, rating):
        """Atualiza a avaliação quando uma estrela é clicada"""
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
        
        # Se clicar na mesma estrela, remove a avaliação
        if found.avaliacao == str(rating):
            found.avaliacao = ""
        else:
            found.avaliacao = str(rating)

        # atualiza CSV apenas se não estiver em modo UI_ONLY
        if not UI_ONLY_MODE:
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
        
        # Recarrega as mensagens para atualizar a visualização das estrelas
        self.reload_chat_messages()

    def on_rating_changed(self, mensagem_id, combo_index):
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
        if combo_index == 0:
            found.avaliacao = ""
        else:
            found.avaliacao = str(combo_index)

        # atualiza CSV (lê tudo, altera linha correspondente)
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

    def load_chats_from_csv(self):
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
        # Ensure the bubble is visible and set to the final response
        bot_bubble.setVisible(True)
        bot_bubble.setText(response)
        user_msg.resposta_bot = response

        if not UI_ONLY_MODE:
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

    def set_sending_state(self, sending: bool):
        self.send_button.setDisabled(sending)
        self.text_input.setDisabled(sending)

    def on_add_documents(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar documentos",
            "",
            "PDF files (*.pdf)"
        )

        if not files:
            return

        # Progress dialog (non-blocking)
        self.ingest_dialog = QProgressDialog(
            "Vetorizando documentos…",
            None,
            0,
            0,
            self
        )
        self.ingest_dialog.setWindowTitle("Processando")
        self.ingest_dialog.setWindowModality(Qt.WindowModal)
        self.ingest_dialog.setCancelButton(None)
        self.ingest_dialog.show()

        # Start worker
        self.ingest_worker = DocumentIngestWorker(files)
        self.ingest_worker.finished.connect(self.on_ingest_finished)
        self.ingest_worker.error.connect(self.on_ingest_error)
        self.ingest_worker.start()

    def on_ingest_finished(self):
        self.ingest_dialog.close()
        QMessageBox.information(
            self,
            "Concluído",
            "Documentos adicionados e vetorizados com sucesso."
        )
        
    def on_ingest_error(self, message):
        self.ingest_dialog.close()
        QMessageBox.critical(
            self,
            "Erro",
            f"Falha ao processar documentos:\n{message}"
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatBotUI()
    window.show()
    sys.exit(app.exec_())
