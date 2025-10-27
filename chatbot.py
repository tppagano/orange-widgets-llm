import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QScrollArea, QLabel, QFrame
)
from PyQt5.QtCore import Qt
import llm

class ChatBotUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Chatbot")
        self.setGeometry(300, 100, 500, 600)

        # Layout principal
        main_layout = QVBoxLayout(self)

        # Área de scroll para mensagens
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        # Conteúdo dentro do scroll
        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.addStretch(1)

        self.scroll_area.setWidget(self.chat_content)
        main_layout.addWidget(self.scroll_area)

        # Campo de texto + botão enviar
        input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(50)
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self.send_message)

        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_button)

        main_layout.addLayout(input_layout)

    def add_message(self, text, sender="user"):
        """Adiciona mensagem no chat."""
        message = QLabel(text)
        message.setWordWrap(True)
        message.setFrameShape(QFrame.Panel)
        message.setFrameShadow(QFrame.Raised)
        message.setStyleSheet(
            "padding: 8px; border-radius: 8px; background-color: %s;" % (
                "#DCF8C6" if sender == "user" else "#FFFFFF"
            )
        )

        # Layout horizontal para alinhar esquerda/direita
        msg_layout = QHBoxLayout()
        if sender == "user":
            msg_layout.addStretch()
            msg_layout.addWidget(message)
        else:
            msg_layout.addWidget(message)
            msg_layout.addStretch()

        self.chat_layout.insertLayout(self.chat_layout.count() - 1, msg_layout)

        # Auto-scroll para última mensagem
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def send_message(self):
        """Quando clica em enviar"""
        text = self.text_input.toPlainText().strip()
        if text:
            self.add_message(text, sender="user")
            self.text_input.clear()

            # Resposta simulada do chatbot
            self.add_message("Resposta do bot para: " + llm.chain.invoke({'question': text}), sender="bot")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatBotUI()
    window.show()
    sys.exit(app.exec_())
