# chatbot_gui_fix.py
import sys
import os
import csv

# DEBUG MODE: Set to True to disable LLM loading and use mock responses
DEBUG_MODE = True

if not DEBUG_MODE:
    import llm

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QFrame, QScrollArea, QTextEdit, QComboBox,
    QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer



CSV_FILE = "conversas.csv"
LLM_DEFAULT = "gemma3"
LLM_OPTIONS = ["gemma3", "gpt-4o-mini", "gpt-4o", "llama2", "local-llm"]


def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["mensagem_id", "chat_id", "mensagem_usuario", "resposta_bot", "llm_usada", "avaliacao"])


def read_all_rows():
    rows = []
    if not os.path.exists(CSV_FILE):
        return rows
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def write_all_rows(rows):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["mensagem_id", "chat_id", "mensagem_usuario", "resposta_bot", "llm_usada", "avaliacao"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def append_row(row):
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["mensagem_id", "chat_id", "mensagem_usuario", "resposta_bot", "llm_usada", "avaliacao"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
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
        self.mensagem_usuario = mensagem_usuario
        self.resposta_bot = resposta_bot
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
        if not text:
            return
        if self.current_chat_id is None:
            QMessageBox.warning(self, "Sem conversa", "Nenhuma conversa selecionada.")
            return

        chat = self.chats[self.current_chat_id]
        llm_used = chat.llm
        mid = next_message_id()

        # adiciona mensagem do usuário (temporariamente sem resposta)
        user_msg = ChatMessage(mensagem_id=mid, chat_id=self.current_chat_id,
                               mensagem_usuario=text, resposta_bot="", llm_usada=llm_used, avaliacao="")
        chat.messages.append(user_msg)
        self._add_message_widget_to_ui(user_msg)
        self.text_input.clear()
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

        # --- Aqui você integraria com a LLM real ---
        if DEBUG_MODE:
            # Resposta mockada para testes rápidos de UI
            bot_response_text = f"Resposta mockada ({llm_used}) para: '{text}'. Esta é uma resposta de teste para avaliar a interface do chatbot sem carregar o modelo LLM."
        else:
            # Resposta real do LLM
            bot_response_text = f"Resposta ({llm_used}) para: {llm.chain.invoke({'question': text})}"
        
        user_msg.resposta_bot = bot_response_text

        # salva no CSV
        row = {
            "mensagem_id": user_msg.mensagem_id,
            "chat_id": user_msg.chat_id,
            "mensagem_usuario": user_msg.mensagem_usuario,
            "resposta_bot": user_msg.resposta_bot,
            "llm_usada": user_msg.llm_usada,
            "avaliacao": user_msg.avaliacao
        }
        append_row(row)

        # recarrega para mostrar resposta e selector
        self.reload_chat_messages()

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

        # atualiza CSV
        rows = read_all_rows()
        changed = False
        for r in rows:
            if str(r.get("mensagem_id", "")) == mid:
                r["avaliacao"] = found.avaliacao
                changed = True
                break
        if changed:
            write_all_rows(rows)
        else:
            row = {
                "mensagem_id": found.mensagem_id,
                "chat_id": found.chat_id,
                "mensagem_usuario": found.mensagem_usuario,
                "resposta_bot": found.resposta_bot,
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
            write_all_rows(rows)
        else:
            row = {
                "mensagem_id": found.mensagem_id,
                "chat_id": found.chat_id,
                "mensagem_usuario": found.mensagem_usuario,
                "resposta_bot": found.resposta_bot,
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
                mensagem_usuario=r.get("mensagem_usuario", ""),
                resposta_bot=r.get("resposta_bot", ""),
                llm_usada=r.get("llm_usada", LLM_DEFAULT) or LLM_DEFAULT,
                avaliacao=r.get("avaliacao", "") or ""
            )
            self.chats[cid].messages.append(msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatBotUI()
    window.show()
    sys.exit(app.exec_())
