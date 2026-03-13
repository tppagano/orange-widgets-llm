"""
Orange3 LLM Widget
==================

Widget for Language Model configuration and inference.
"""

from AnyQt.QtWidgets import QHBoxLayout, QLabel, QWidget
from AnyQt.QtCore import Qt
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


LLM_OPTIONS = {
    "gemma3":      {"type": "ollama", "model": "gemma3",      "context_limit": 4096},
    "llama3.1:8b": {"type": "ollama", "model": "llama3.1:8b", "context_limit": 4096},
    "gpt-4o-mini": {"type": "openai", "model": "gpt-4o-mini", "context_limit": 16384},
    "gpt-4o":      {"type": "openai", "model": "gpt-4o",      "context_limit": 32768},
}

PROMPT_OVERHEAD  = 400   # tokens reserved for template + average chat history
AVG_CHUNK_TOKENS = 150   # ~600 chars / 4  (chars-to-tokens estimate)


class OWLLM(widget.OWWidget):
    name = "LLM"
    description = "Language Model configuration for chat"
    icon = "icons/llm.svg"
    priority = 90
    keywords = ["llm", "language model", "ai", "gpt", "ollama"]
    
    want_main_area = False
    resizing_enabled = False
    
    # Settings
    selected_llm    = settings.Setting(1)
    temperature_pct = settings.Setting(4)   # int 1-7 → temperature = value * 0.1
    temperature     = settings.Setting(0.4)
    max_tokens      = settings.Setting(2048)
    streaming       = settings.Setting(True)
    show_advanced   = settings.Setting(False)
    
    class Inputs:
        retriever = Input("Retriever", object)
    
    class Outputs:
        llm_config = Output("LLM Config", dict)
    
    def __init__(self):
        super().__init__()
        
        self.retriever = None
        self.llm_config = None
        self.max_tokens_spin = None
        self.adv_inner = None

        self._setup_gui()
        self._sync_temperature_from_slider()
        self._update_token_cap()
        self._update_config()
    
    def _setup_gui(self):
        # Top row: regular controls (kept compact and horizontal)
        top_row = QWidget(self.controlArea)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(6)
        self.controlArea.layout().addWidget(top_row)

        # Model selection
        model_box = gui.widgetBox(top_row, "Model Selection")
        top_row_layout.addWidget(model_box, 1)

        gui.comboBox(
            model_box, self, "selected_llm",
            label="Model:",
            items=list(LLM_OPTIONS.keys()),
            callback=self._on_model_changed,
        )

        self.model_info_label = gui.label(model_box, self, "")
        self._update_model_info()

        # Response style — temperature slider
        tone_box = gui.widgetBox(top_row, "Response Style")
        top_row_layout.addWidget(tone_box, 1)
        self.tone_box = tone_box
        gui.hSlider(
            tone_box, self, "temperature_pct",
            minValue=1, maxValue=7, step=1,
            label="Tone:",
            createLabel=False,
            ticks=True,
            callback=self._on_temperature_slider_changed,
        )
        lbl_widget = QWidget()
        lbl_layout = QHBoxLayout(lbl_widget)
        lbl_layout.setContentsMargins(8, 0, 8, 2)
        for txt, align in [
            ("Precise",  Qt.AlignLeft),
            ("Balanced", Qt.AlignCenter),
            ("Creative", Qt.AlignRight),
        ]:
            lbl = QLabel(txt)
            lbl.setAlignment(align)
            lbl_layout.addWidget(lbl)
        tone_box.layout().addWidget(lbl_widget)

        # RAG status
        rag_box = gui.widgetBox(self.controlArea, "RAG Status")
        self.rag_status_label = gui.label(rag_box, self, "Waiting for retriever...")

        # Info
        info_box = gui.widgetBox(self.controlArea, "Info")
        self.info_label = gui.label(
            info_box, self,
            "This widget configures the LLM\n"
            "for use in the Chat widget.\n\n"
            "Connect a Retriever from the\n"
            "RAG widget (required)."
        )

        # Advanced settings (bottom section)
        gui.checkBox(
            self.controlArea, self, "show_advanced",
            label="Show advanced settings",
            callback=self._on_advanced_visibility_changed,
        )

        self.adv_inner = gui.widgetBox(self.controlArea, "Advanced Settings")

        gui.doubleSpin(
            self.adv_inner, self, "temperature",
            minv=0.0, maxv=2.0, step=0.1,
            label="Manual temperature:",
            callback=self._on_manual_temperature_changed,
        )

        self.max_tokens_spin = gui.spin(
            self.adv_inner, self, "max_tokens",
            minv=800, maxv=32768, step=256,
            label="Max tokens:",
            callback=self._update_config,
        )
        self.token_info_label = gui.label(self.adv_inner, self, "")
        self.token_info_label.setWordWrap(True)
        self.token_info_label.setStyleSheet("color: gray; font-size: 10px;")

        gui.checkBox(
            self.adv_inner, self, "streaming",
            label="Enable streaming",
            callback=self._update_config,
        )
        self.adv_inner.setVisible(self.show_advanced)
        self.tone_box.setEnabled(not self.show_advanced)
    
    def _update_model_info(self):
        model_keys = list(LLM_OPTIONS.keys())
        model_name = model_keys[self.selected_llm]
        config = LLM_OPTIONS[model_name]
        # Keep this line compact to avoid horizontal growth when toggling advanced mode.
        self.model_info_label.setText(f"Type: {config['type']}")

    def _on_model_changed(self):
        self._update_model_info()
        self._update_token_cap()
        self._update_config()

    def _sync_temperature_from_slider(self):
        self.temperature = round(self.temperature_pct * 0.1, 1)

    def _on_temperature_slider_changed(self):
        self._sync_temperature_from_slider()
        self._update_config()

    def _on_manual_temperature_changed(self):
        self.temperature = min(2.0, max(0.0, round(self.temperature, 1)))
        # Keep slider as coarse style indicator even when manual temp is outside 0.1-0.7
        self.temperature_pct = min(7, max(1, int(round(self.temperature * 10))))
        self._update_config()

    def _on_advanced_visibility_changed(self):
        if self.adv_inner is not None:
            self.adv_inner.setVisible(self.show_advanced)
        if hasattr(self, "tone_box"):
            self.tone_box.setEnabled(not self.show_advanced)
        self._update_model_info()
        self._update_token_cap()
        self._update_config()

    def _update_token_cap(self):
        """Recompute max_tokens ceiling: model context minus prompt and retrieval overhead."""
        model_keys = list(LLM_OPTIONS.keys())
        context_limit = LLM_OPTIONS[model_keys[self.selected_llm]]["context_limit"]

        top_k = 5
        if self.retriever is not None and hasattr(self.retriever, "search_kwargs"):
            top_k = self.retriever.search_kwargs.get("k", 5)

        retrieved_tokens = top_k * AVG_CHUNK_TOKENS
        available_context = max(1, context_limit - PROMPT_OVERHEAD - retrieved_tokens)
        suggested_max_tokens = min(800, available_context)

        if self.max_tokens_spin is not None:
            self.max_tokens_spin.setMinimum(1)
            self.max_tokens_spin.setMaximum(available_context)

        # Advanced OFF: enforce automatic max_tokens from the formula.
        # Advanced ON: user can choose any value within the allowed range.
        if not self.show_advanced:
            self.max_tokens = suggested_max_tokens
        elif self.max_tokens > available_context or self.max_tokens < 1:
            self.max_tokens = suggested_max_tokens

        if hasattr(self, "token_info_label"):
            if self.show_advanced:
                self.token_info_label.setText(
                    f"{context_limit:,} - {PROMPT_OVERHEAD} prompt overhead "
                    f"- {retrieved_tokens} retrieved ({top_k}x{AVG_CHUNK_TOKENS}) "
                    f"= {available_context:,} available (suggested max_tokens: {suggested_max_tokens:,})"
                )
            else:
                self.token_info_label.setText("")

    @Inputs.retriever
    def set_retriever(self, retriever):
        self.retriever = retriever
        if retriever is None:
            self.rag_status_label.setText("⚠ Waiting for retriever...")
            self.info.set_input_summary(self.info.NoInput)
        else:
            self.rag_status_label.setText("✓ Retriever connected")
            self.info.set_input_summary("Retriever connected")
        self._update_token_cap()
        self._update_config()

    def _update_config(self):
        model_keys = list(LLM_OPTIONS.keys())
        model_name = model_keys[self.selected_llm]
        model_config = LLM_OPTIONS[model_name]

        if self.retriever is None:
            self.Outputs.llm_config.send(None)
            self.info.set_output_summary(self.info.NoOutput)
            return

        effective_temperature = (
            self.temperature
            if self.show_advanced
            else round(self.temperature_pct * 0.1, 1)
        )

        self.llm_config = {
            "model_name":  model_name,
            "model_type":  model_config["type"],
            "model":       model_config["model"],
            "temperature": effective_temperature,
            "max_tokens":  self.max_tokens,
            "streaming":   self.streaming,
            "retriever":   self.retriever,
            "rag_enabled": True,
        }
        self.Outputs.llm_config.send(self.llm_config)
        self.info.set_output_summary(f"{model_name} with RAG")


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWLLM).run()
